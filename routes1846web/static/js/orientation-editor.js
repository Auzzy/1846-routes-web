function createOrientationEditor(imageUrl) {
    var OrientationEditor = Handsontable.editors.DropdownEditor.prototype.extend();
    
    OrientationEditor.prototype.updateChoicesList = function(choicesList) {
        var self = this;
    
        self.orientationByIndex = {};
    
        choicesList.slice().forEach((orientation, index) => {
            // Do some basic input sanitation
            var tileId = this.instance.getDataAtCell(this.row, 1)
            orientation = parseInt(this.stripValueIfNeeded(orientation), 10).toString();
    
            choicesList.splice(choicesList.indexOf(orientation), 1);
    
            img = document.createElement('img');
            img.style.cssText = "width: 40px; height: 40 px;";
            
            var tileIdStr = tileId.toString().padStart(3, "0");
            var orientationStr = orientation.toString();
            img.src = `${imageUrl}/${tileIdStr}-${orientationStr}.png`;
    
            choicesList.push(img.outerHTML);
            self.orientationByIndex[index] = orientation;
        });
    
        Handsontable.editors.DropdownEditor.prototype.updateChoicesList.apply(self, arguments);
    }
    
    // TODO: Determine the right way to handle index == -1
    OrientationEditor.prototype.setValue = function(newVal) {
        var index = this.strippedChoices.indexOf(newVal);
        if (index !== -1) {
            Handsontable.editors.DropdownEditor.prototype.setValue.apply(this, [parseInt(this.orientationByIndex[index], 10).toString()]);
        } else {
            Handsontable.editors.DropdownEditor.prototype.setValue.apply(this, arguments);
        }
    }
    
    OrientationEditor.prototype.getValue = function() {
        return Handsontable.editors.DropdownEditor.prototype.getValue.apply(this);
    }

    OrientationEditor.prototype.getDropdownHeight = function() {
      const rowHeight = 45;
      const visibleRows = this.cellProperties.visibleRows;
    
      return this.strippedChoices.length >= visibleRows ? (visibleRows * rowHeight) : (this.strippedChoices.length * rowHeight) + 8;
    };

    
    return OrientationEditor;
}