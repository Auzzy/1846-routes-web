function createTileEditor(imageUrl) {
    var TileEditor = Handsontable.editors.DropdownEditor.prototype.extend();
    
    TileEditor.prototype.updateChoicesList = function(choicesList) {
        var self = this;
    
        self.tileIdByIndex = {};
    
        choicesList.slice().forEach((tileId, index) => {
            // Do some basic input sanitation
            tileId = parseInt(this.stripValueIfNeeded(tileId), 10).toString();
    
            choicesList.splice(choicesList.indexOf(tileId), 1);
    
            img = document.createElement('img');
            img.style.cssText = "width: 40px; height: 40 px;";
            
            var tileIdStr = tileId.padStart(3, "0");
            img.src = `${imageUrl}/${tileIdStr}.png`;
    
            choicesList.push(img.outerHTML);
            self.tileIdByIndex[index] = tileId;
        });
    
        Handsontable.editors.DropdownEditor.prototype.updateChoicesList.apply(self, arguments);
    }
    
    // TODO: Determine the right way to handle index == -1
    TileEditor.prototype.setValue = function(newVal) {
        var index = this.strippedChoices.indexOf(newVal);
        if (index !== -1) {
            Handsontable.editors.DropdownEditor.prototype.setValue.apply(this, [parseInt(this.tileIdByIndex[index], 10).toString()]);
        } else {
            Handsontable.editors.DropdownEditor.prototype.setValue.apply(this, arguments);
        }
    }
    
    TileEditor.prototype.getValue = function() {
        return Handsontable.editors.DropdownEditor.prototype.getValue.apply(this);
    }

    TileEditor.prototype.getDropdownHeight = function() {
      const rowHeight = 45;
      const visibleRows = this.cellProperties.visibleRows;
    
      return this.strippedChoices.length >= visibleRows ? (visibleRows * rowHeight) : (this.strippedChoices.length * rowHeight) + 8;
    };
    
    return TileEditor;
}