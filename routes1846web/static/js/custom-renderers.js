function customTileDropdownRenderer(imagesBaseUrl) {
    return function(instance, td, row, col, prop, value, cellProperties) {
        Handsontable.renderers.DropdownRenderer.apply(this, arguments);
    
        if (value !== null) {
            td.removeChild(td.childNodes[1]);
    
            img = document.createElement('img');
            img.style.cssText = "width: 40px; height: 40 px;";
            // {# img.src = "{{ url_for('static', filename="images") }}/" + value.toString().padStart(3, "0") + ".png"; #}

            let tileIdStr = value.toString().padStart(3, "0");
            img.src = `${imagesBaseUrl}/${tileIdStr}.png`;
    
            td.appendChild(img);
        }
    
        return td;
    };
}

function customOrientationDropdownRenderer(imagesBaseUrl) {
    return function(instance, td, row, col, prop, value, cellProperties) {
        Handsontable.renderers.DropdownRenderer.apply(this, arguments);
    
        if (value !== null) {
            td.removeChild(td.childNodes[1]);

            var tileId = instance.getDataAtCell(row, 1);

            img = document.createElement('img');
            img.style.cssText = "width: 40px; height: 40 px;";

            var tileIdStr = tileId.toString().padStart(3, "0");
            var orientationStr = value.toString();
            img.src = `${imagesBaseUrl}/${tileIdStr}-${orientationStr}.png`;
    
            td.appendChild(img);
        }
    
        return td;
    };
}