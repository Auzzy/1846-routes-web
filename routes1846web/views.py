import json
import tempfile

from flask import jsonify, render_template, request
from routes1846 import boardstate, find_best_routes, railroads

from routes1846web.routes1846web import app


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
    return render_template("index.html",
            railroads_colnames=json.dumps(RAILROADS_COLUMN_NAMES),
            placed_tiles_colnames=json.dumps(PLACED_TILES_COLUMN_NAMES))

@app.route("/calculate", methods=["POST"])
def calculate():
    railroads_state_rows = json.loads(request.form.get("railroads-json"))
    board_state_rows = json.loads(request.form.get("board-state-json"))
    railroad_name = request.form["railroad-name"]

    board = boardstate.load([dict(zip(boardstate.FIELDNAMES, row)) for row in board_state_rows if any(val for val in row)])
    railroad_dict = railroads.load(board, [dict(zip(railroads.FIELDNAMES, row)) for row in railroads_state_rows if any(val for val in row)])

    board.validate()

    best_routes = find_best_routes(board, railroad_dict, railroad_dict[railroad_name])
    routes_json = {}
    for train, route_to_val in best_routes.items():
        routes_json[str(train)] = {
            "route": [str(space.cell) for space in route_to_val[0]],
            "value": route_to_val[1]
        }
    return jsonify(routes_json)