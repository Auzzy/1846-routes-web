import json
import tempfile

from flask import jsonify, render_template, request

from routes1846 import boardstate, find_best_routes, railroads, tiles
from routes1846.cell import _CELL_DB, CHICAGO_CELL, Cell

from routes1846web.routes1846web import app


CHICAGO_STATION_EDGES = {1, 4, 5, 6}
RAILROAD_NAMES = [
    "Baltimore & Ohio",
    "Illinois Central",
    "New York Central",
    "Chesapeake & Ohio",
    "Erie",
    "Grand Trunk",
    "Pennsylvania"
]

RAILROADS_COLUMN_MAP = {
    "name": "name",
    "trains": "trains",
    "stations": "stations",
    "chicago_station_exit_coord": "chicago station side"
}

PLACED_TILES_COLUMN_MAP = {
    "coord": "coordinate",
    "tile_id": "tile number",
    "orientation": "orientation"
}

RAILROADS_COLUMN_NAMES = [RAILROADS_COLUMN_MAP[colname] for colname in railroads.FIELDNAMES]
PLACED_TILES_COLUMN_NAMES = [PLACED_TILES_COLUMN_MAP[colname] for colname in boardstate.FIELDNAMES]

@app.route("/")
def main():
    tile_coords = []
    for row, cols in sorted(_CELL_DB.items()):
        for col in sorted(cols):
            coord = "{}{}".format(row, col)
            space = _get_space(coord)
            if not space or (space.phase and space.phase < 4):
                tile_coords.append(coord)

    return render_template("index.html",
            railroads_colnames=json.dumps(RAILROADS_COLUMN_NAMES),
            placed_tiles_colnames=json.dumps(PLACED_TILES_COLUMN_NAMES),
            tile_coords=json.dumps(tile_coords),
            railroad_names=json.dumps(RAILROAD_NAMES))

@app.route("/calculate", methods=["POST"])
def calculate():
    railroads_state_rows = json.loads(request.form.get("railroads-json"))
    board_state_rows = json.loads(request.form.get("board-state-json"))
    railroad_name = request.form["railroad-name"]

    board = boardstate.load([dict(zip(boardstate.FIELDNAMES, row)) for row in board_state_rows if any(val for val in row)])
    railroad_dict = railroads.load(board, [dict(zip(railroads.FIELDNAMES, row)) for row in railroads_state_rows if any(val for val in row)])
    board.validate()

    if railroad_name not in railroad_dict:
        raise ValueError("Railroad chosen: \"{}\". Valid railroads: {}".format(railroad_name, ", ".join(railroad_dict.keys())))

    best_routes = find_best_routes(board, railroad_dict, railroad_dict[railroad_name])
    routes_json = {}
    for train, route_to_val in best_routes.items():
        routes_json[str(train)] = {
            "route": [str(space.cell) for space in route_to_val[0]],
            "value": route_to_val[1]
        }
    return jsonify(routes_json)

def _get_space(coord):
    from routes1846 import boardtile
    space = None
    for tile in boardtile.load():
        if str(tile.cell) == coord:
            return tile

def _get_orientations(coord, tile_id):
    cell = Cell.from_coord(coord)

    tile = tiles.get_tile(tile_id)
    
    from routes1846.placedtile import PlacedTile
    orientations = []
    for orientation in range(1, 7):
        try:
            paths = PlacedTile.get_paths(cell, tile, orientation)
            orientations.append(orientation)
        except ValueError:
            continue

    return orientations

@app.route("/board/legal-tiles")
def legal_tiles():
    query = request.args.get("query")
    coord = request.args.get("coord")

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

    return jsonify({"legal-tile-ids": legal_tile_ids})

@app.route("/board/legal-orientations")
def legal_orientations():
    query = request.args.get("query")
    coord = request.args.get("coord")
    tile_id = request.args.get("tileId")

    orientations = _get_orientations(coord, tile_id)
    return jsonify({"legal-orientations": list(sorted(orientations))})

@app.route("/railroads/trains")
def trains():
    trains = [str(railroads.Train(collect, visit, None)) for collect, visit in sorted(railroads.TRAIN_TO_PHASE)]
    return jsonify({"trains": trains})

@app.route("/railroads/cities")
def cities():
    query = request.args.get("query")

    from routes1846 import boardtile
    cities = [str(tile.cell) for tile in sorted(boardtile.load(), key=lambda tile: tile.cell) if tile.is_city and not tile.is_terminal_city]

    if query:
        cities = [city for city in cities if city.startswith(query)]

    return jsonify({"cities": cities})

@app.route("/railroads/legal-chicago-stations")
def chicago_stations():
    existing_station_edges = {edge for edge in json.loads(request.args.get("stations")) if edge}

    legal_stations = CHICAGO_STATION_EDGES - existing_station_edges
    return jsonify({"chicago-stations": list(legal_stations)})