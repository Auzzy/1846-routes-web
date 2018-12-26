import collections
import json
import logging
import os
import tempfile
import traceback

from flask import jsonify, render_template, request
from flask_mail import Message
from rq import Queue

from routes1846 import board, boardstate, boardtile, find_best_routes, railroads, tiles, LOG as LIB_LOG
from routes1846.cell import _CELL_DB, CHICAGO_CELL, Cell, board_cells

from routes1846web.routes1846web import app, mail
from routes1846web.calculator import redis_conn
from routes1846web.logger import get_logger, init_logger, set_log_format


LOG = get_logger("routes1846web")
init_logger(LOG, "APP_LOG_LEVEL")
set_log_format(LOG)

init_logger(LIB_LOG, "LIB_LOG_LEVEL", 0)
set_log_format(LIB_LOG)

CALCULATOR_QUEUE = Queue(connection=redis_conn)

MESSAGE_BODY_FORMAT = "User: {user}\nComments:\n{comments}"

CHICAGO_STATION_SIDES = (0, 3, 4, 5)
CHICAGO_STATION_COORDS = collections.OrderedDict([(str(CHICAGO_CELL.neighbors[side]), side) for side in CHICAGO_STATION_SIDES])
RAILROAD_NAMES = {
    "Baltimore & Ohio",
    "Illinois Central",
    "New York Central",
    "Chesapeake & Ohio",
    "Erie",
    "Grand Trunk",
    "Pennsylvania"
}

RAILROADS_COLUMN_MAP = {
    "name": "name",
    "trains": "trains",
    "stations": "stations",
    "chicago_station_exit_coord": "chicago station side"
}

PLACED_TILES_COLUMN_MAP = {
    "coord": "coordinate",
    "tile_id": "tile",
    "orientation": "orientation"
}

PRIVATE_COMPANIES = (
    "Steamboat Company",
    "Meat Packing Company",
    "Mail Contract"
)

PRIVATE_COMPANY_TO_COLUMN = {
    "Steamboat Company": "port_coord",
    "Meat Packing Company": "meat_packing_coord",
    "Mail Contract": "has_mail_contract"
}

RAILROADS_COLUMN_NAMES = [RAILROADS_COLUMN_MAP[colname] for colname in railroads.RAILROAD_FIELDNAMES]
PLACED_TILES_COLUMN_NAMES = [PLACED_TILES_COLUMN_MAP[colname] for colname in boardstate.FIELDNAMES]
PRIVATE_COMPANY_COLUMN_NAMES = ["name", "owner", "token coordinate"]

SEAPORT_COORDS = [str(tile.cell) for tile in sorted(boardtile.load(), key=lambda tile: tile.cell) if tile.port_value]
MEAT_COORDS = [str(tile.cell) for tile in sorted(boardtile.load(), key=lambda tile: tile.cell) if tile.meat_value]

_BASE_BOARD = board.Board.load()

_TILE_COORDS = []

def get_tile_coords():
    global _TILE_COORDS

    if not _TILE_COORDS:
        tile_coords = []
        for row, cols in sorted(_CELL_DB.items()):
            for col in sorted(cols):
                coord = "{}{}".format(row, col)
                space = _get_space(coord)
                if not space or (space.phase is not None and space.phase < 4):
                    tile_coords.append(coord)
        _TILE_COORDS = tile_coords
    return _TILE_COORDS

@app.route("/")
def main():
    return render_template("index.html",
            railroads_colnames=RAILROADS_COLUMN_NAMES,
            private_company_rownames=PRIVATE_COMPANIES,
            private_company_colnames=PRIVATE_COMPANY_COLUMN_NAMES,
            placed_tiles_colnames=PLACED_TILES_COLUMN_NAMES,
            tile_coords=get_tile_coords())

def _build_railroad_rows(railroads_state_rows, private_companies_rows):
    railroad_rows = []
    for railroad_row in railroads_state_rows:
        railroad_name = railroad_row[railroads.RAILROAD_FIELDNAMES.index("name")]
        if any(val for val in railroad_row):
            railroad_private_companies = [None] * len(PRIVATE_COMPANIES)
            for private_row in private_companies_rows:
                row = railroads.PRIVATE_COMPANY_FIELDNAMES.index(PRIVATE_COMPANY_TO_COLUMN[private_row[PRIVATE_COMPANY_COLUMN_NAMES.index("name")]])
                company_owner = private_row[PRIVATE_COMPANY_COLUMN_NAMES.index("owner")]
                if company_owner and railroad_name == company_owner:
                    company_name = private_row[PRIVATE_COMPANY_COLUMN_NAMES.index("name")]
                    token_coord = private_row[PRIVATE_COMPANY_COLUMN_NAMES.index("token coordinate")]
                    railroad_private_companies[row] = True if company_name.lower() == "mail contract" else token_coord
            railroad_row.extend(railroad_private_companies)
            railroad_rows.append(dict(zip(railroads.FIELDNAMES, railroad_row)))

    return railroad_rows

@app.route("/calculate", methods=["POST"])
def calculate():
    railroads_state_rows = json.loads(request.form.get("railroads-json"))
    private_companies_rows = json.loads(request.form.get("private-companies-json"))
    board_state_rows = json.loads(request.form.get("board-state-json"))
    railroad_name = request.form["railroad-name"]

    LOG.info("Calculate request.")
    LOG.info("Target railroad: {}".format(railroad_name))
    LOG.info("Private companies: {}".format(private_companies_rows))
    LOG.info("Railroad input: {}".format(railroads_state_rows))
    LOG.info("Board input: {}".format(board_state_rows))

    for row in railroads_state_rows:
        if row[3]:
            row[3] = CHICAGO_STATION_COORDS[row[3]]

    job = CALCULATOR_QUEUE.enqueue(calculate_worker, railroads_state_rows, private_companies_rows, board_state_rows, railroad_name, timeout="5m")

    return jsonify({"jobId": job.id})

@app.route("/calculate/result")
def calculate_result():
    routes_json = _get_calculate_result(request.args.get("jobId"))

    LOG.info("Calculate response: {}".format(routes_json))

    return jsonify(routes_json)

def _get_calculate_result(job_id):
    routes_json = {}

    job = CALCULATOR_QUEUE.fetch_job(job_id)
    # If job is None, it means the job ID couldn't be found, either because it's invalid, or the job was cancelled.
    if job:
        if job.is_failed:
            # The job experienced an error
            if not job.exc_info:
                # The error info hasn't propagated yet, so act as if the job is still in progress
                routes_json["jobId"] = job_id
            else:
                exc_info = json.loads(job.exc_info)
                routes_json["error"] = {
                    "message": "An error occurred during route calculation: {}".format(exc_info["message"]),
                    "traceback": exc_info["traceback"]
                }

        elif job.is_finished:
            routes_json["routes"] = []
            for route in job.result:
                routes_json["routes"].append([
                    str(route.train),
                    [str(space.cell) for space in route],
                    route.value
                ])
        else:
            # The job is in progress
            routes_json["jobId"] = job_id

    return routes_json

@app.route("/calculate/cancel", methods=["POST"])
def cancel_calculate_request():
    job_id = request.form.get("jobId")
    job = CALCULATOR_QUEUE.fetch_job(job_id)
    if job:
        job.delete()
    return jsonify({})

def calculate_worker(railroads_state_rows, private_companies_rows, board_state_rows, railroad_name):
    board = boardstate.load([dict(zip(boardstate.FIELDNAMES, row)) for row in board_state_rows if any(val for val in row)])
    railroad_dict = railroads.load(board, _build_railroad_rows(railroads_state_rows, private_companies_rows))
    board.validate()

    if railroad_name not in railroad_dict:
        raise ValueError("Railroad chosen: \"{}\". Valid railroads: {}".format(railroad_name, ", ".join(railroad_dict.keys())))

    return find_best_routes(board, railroad_dict, railroad_dict[railroad_name])

def _get_space(coord):
    space = None
    for tile in boardtile.load():
        if str(tile.cell) == coord:
            return tile

def _get_orientations(coord, tile_id):
    cell = Cell.from_coord(coord)

    tile = tiles.get_tile(tile_id)
    
    from routes1846.placedtile import PlacedTile
    orientations = []
    for orientation in range(0, 6):
        try:
            _BASE_BOARD._validate_place_tile_neighbors(cell, tile, orientation)
        except ValueError:
            continue

        orientations.append(orientation)

    return orientations

@app.route("/board/tile-coords")
def legal_tile_coords():
    LOG.info("Legal tile coordinates request.")

    current_coord = request.args.get("coord")
    existing_tile_coords = {coord for coord in json.loads(request.args.get("tile_coords")) if coord}

    legal_tile_coordinates = set(get_tile_coords()) - existing_tile_coords
    if current_coord:
        legal_tile_coordinates.add(current_coord)

    LOG.info("Legal tile coordinates response: {}".format(legal_tile_coordinates))

    return jsonify({"tile-coords": list(sorted(legal_tile_coordinates))})

@app.route("/board/tile-image")
def board_tile_image():
    tile_id = request.args.get("tileId")
    return url_for('static', filename='images/{:03}'.format(int(tile_id)))

@app.route("/board/legal-tiles")
def legal_tiles():
    query = request.args.get("query")
    coord = request.args.get("coord")

    LOG.info("Legal tiles request for {} (query: {}).".format(coord, query))

    space = _get_space(coord)

    from routes1846 import tiles
    legal_tile_ids = []
    for tile in tiles._load_all().values():
        if not space:
            if tile.is_city or tile.is_z or tile.is_chicago:
                continue
        elif tile.phase <= space.phase:
            continue
        elif space.is_city != tile.is_city or space.is_z != tile.is_z or space.is_chicago != tile.is_chicago:
            continue

        if _get_orientations(coord, tile.id):
            legal_tile_ids.append(tile.id)

    legal_tile_ids.sort()
    if query:
        legal_tile_ids = [tile_id for tile_id in legal_tile_ids if str(tile_id).startswith(query)]

    LOG.info("Legal tiles response for {} (query: {}): {}".format(coord, query, legal_tile_ids))

    return jsonify({"legal-tile-ids": legal_tile_ids})

@app.route("/board/legal-orientations")
def legal_orientations():
    query = request.args.get("query")
    coord = request.args.get("coord")
    tile_id = request.args.get("tileId")

    LOG.info("Legal orientations request for {} at {} (query: {}).".format(tile_id, coord, query))

    orientations = _get_orientations(coord, tile_id)

    LOG.info("Legal orientations response for {} at {} (query: {}): {}".format(tile_id, coord, query, orientations))

    return jsonify({"legal-orientations": list(sorted(orientations))})

@app.route("/railroads/legal-railroads")
def legal_railroads():
    LOG.info("Legal railroads request.")

    existing_railroads = {railroad for railroad in json.loads(request.args.get("railroads")) if railroad}

    legal_railroads = RAILROAD_NAMES - existing_railroads

    LOG.info("Legal railroads response: {}".format(legal_railroads))

    return jsonify({"railroads": list(sorted(legal_railroads))})

@app.route("/railroads/trains")
def trains():
    LOG.info("Train request.")

    trains = [str(railroads.Train(collect, visit, None)) for collect, visit in sorted(railroads.TRAIN_TO_PHASE)]

    LOG.info("Train response: {}".format(trains))

    return jsonify({"trains": trains})

@app.route("/railroads/cities")
def cities():
    query = request.args.get("query")

    LOG.info("City request (query: {}).".format(query))

    from routes1846 import boardtile
    cities = [str(tile.cell) for tile in sorted(boardtile.load(), key=lambda tile: tile.cell) if tile.is_city and not tile.is_terminal_city]

    if query:
        cities = [city for city in cities if city.startswith(query)]

    LOG.info("City response (query: {}): {}".format(query, cities))

    return jsonify({"cities": cities})

@app.route("/railroads/legal-chicago-stations")
def chicago_stations():
    LOG.info("Legal Chicago stations request.")

    existing_station_coords = {coord for coord in json.loads(request.args.get("stations")) if coord}

    legal_stations = list(sorted(set(CHICAGO_STATION_COORDS.keys()) - existing_station_coords))

    LOG.info("Legal Chicago stations response: {}".format(legal_stations))

    return jsonify({"chicago-stations": legal_stations})

@app.route("/railroads/legal-token-coords")
def legal_token_coords():
    company_name = request.args.get("companyName")

    LOG.info("Legal %s token coordinate request.", company_name)

    if company_name.lower() == "steamboat company":
        coords = SEAPORT_COORDS
    elif company_name.lower() == "meat packing company":
        coords = MEAT_COORDS
    else:
        raise ValueError("Received unsupport private company name: {}".format(company_name))

    LOG.info("Legal %s token coordinate response: %s", company_name, coords)

    return jsonify({"coords": coords})


def _build_general_message():
    railroad_headers = json.loads(request.form.get("railroadHeaders"))
    railroads_data = json.loads(request.form.get("railroadData"))
    private_companies_headers = json.loads(request.form.get("privateCompaniesHeaders"))
    private_companies_data = json.loads(request.form.get("privateCompaniesData"))
    placed_tiles_headers = json.loads(request.form.get("placedTilesHeaders"))
    placed_tiles_data = json.loads(request.form.get("placedTilesData"))
    user_email = request.form.get("email")
    user_comments = request.form.get("comments")
    email_subject = request.form.get("subject")

    railroads_json = [dict(zip(railroad_headers, row)) for row in railroads_data if any(row)]
    private_companies_json = [dict(zip(private_companies_headers, row)) for row in private_companies_data]
    placed_tiles_json = [dict(zip(placed_tiles_headers, row)) for row in placed_tiles_data if any(row)]

    msg = Message(
        body=MESSAGE_BODY_FORMAT.format(user=user_email, comments=user_comments),
        subject=email_subject,
        sender=app.config.get("MAIL_USERNAME"),
        recipients=[os.environ["BUG_REPORT_EMAIL"]])

    msg.attach("railroads.json", "application/json", json.dumps(railroads_json, indent=4, sort_keys=True))
    msg.attach("private-companies.json", "application/json", json.dumps(private_companies_json, indent=4, sort_keys=True))
    msg.attach("placed-tiles.json", "application/json", json.dumps(placed_tiles_json, indent=4, sort_keys=True))

    return msg

@app.route("/report/general-issue", methods=["POST"])
def report_general_issue():
    mail.send(_build_general_message())
    return ""

@app.route("/report/calc-issue", methods=["POST"])
def report_calc_issue():
    target_railroad = request.form.get("targetRailroad")
    job_id = request.form.get("jobId")

    msg = _build_general_message()

    routes_json = _get_calculate_result(job_id)
    msg.attach("routes.json", "application/json", json.dumps({target_railroad: routes_json}, indent=4, sort_keys=True))

    mail.send(msg)

    return ""

@app.route("/report/tile-issue", methods=["POST"])
def report_tile_issue():
    placed_tiles_headers = json.loads(request.form.get("placedTilesHeaders"))
    placed_tiles_data = json.loads(request.form.get("placedTilesData"))
    coord = request.form.get("coord")
    tiles_json = json.loads(request.form.get("tiles"))
    orientations_json = json.loads(request.form.get("orientations"))
    user_email = request.form.get("email")
    user_comments = request.form.get("comments")
    email_subject = request.form.get("subject")

    msg = Message(
        body=MESSAGE_BODY_FORMAT.format(user=user_email, comments=user_comments),
        subject=email_subject,
        sender=app.config.get("MAIL_USERNAME"),
        recipients=[os.environ["BUG_REPORT_EMAIL"]])

    placed_tiles_json = [dict(zip(placed_tiles_headers, row)) for row in placed_tiles_data if any(row)]

    msg.attach("placed-tiles.json", "application/json", json.dumps(placed_tiles_json, indent=4, sort_keys=True))
    msg.attach("tiles.json", "application/json", json.dumps(tiles_json, indent=4, sort_keys=True))
    msg.attach("orientations.json", "application/json", json.dumps(orientations_json, indent=4, sort_keys=True))
    mail.send(msg)

    return ""