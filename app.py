function doPost(e) {
  try {
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    
    // 1. Target the exact tab: "MPSEDC_New Router Installation"
    var sheets = ss.getSheets();
    var sheet = null;
    for (var s = 0; s < sheets.length; s++) {
      if (sheets[s].getName().indexOf("MPSEDC_New Router Installation") !== -1) {
        sheet = sheets[s];
        break;
      }
    }
    if (!sheet) {
      sheet = ss.getActiveSheet();
    }
    
    var data = JSON.parse(e.postData.contents);
    var todayStr = Utilities.formatDate(new Date(), "Asia/Kolkata", "dd/MM/yyyy");
    var todayShort = Utilities.formatDate(new Date(), "Asia/Kolkata", "dd/MM/yy");
    var targetHost = (data.host_name || "").toString().trim();
    
    function cleanHeader(h) {
      return (h || "").toString().toLowerCase().replace(/[^a-z0-9]/g, "");
    }
    
    // 2. Read all values in the sheet
    var dataRange = sheet.getDataRange();
    var values = dataRange.getValues();
    
    // Find Header Row (checks rows 1 to 5)
    var headerRowIdx = -1;
    for (var r = 0; r < Math.min(6, values.length); r++) {
      var rowClean = values[r].map(cleanHeader);
      if (rowClean.indexOf("hostname") !== -1 || rowClean.indexOf("srno") !== -1) {
        headerRowIdx = r;
        break;
      }
    }
    
    if (headerRowIdx === -1) {
      headerRowIdx = 0; // Default to row 1
    }
    
    // Map column titles to 1-based indices
    var headers = values[headerRowIdx];
    var colMap = {};
    for (var c = 0; c < headers.length; c++) {
      var k = cleanHeader(headers[c]);
      if (k) colMap[k] = c + 1; // 1-based
    }
    
    var colSr     = colMap["srno"] || colMap["sr"] || 1;
    var colDate   = colMap["date"] || 2;
    var colDist   = colMap["dist"] || colMap["district"] || 3;
    var colTehsil = colMap["tehsilblock"] || colMap["tehsil"] || colMap["block"] || 4;
    var colHost   = colMap["hostname"] || colMap["host"] || 5;
    var colWanPe  = colMap["wanippeend"] || colMap["wanippe"] || 9;
    var colWanCpe = colMap["wanipcpe"] || colMap["wancpe"] || 10;
    var colLan    = colMap["lanip"] || colMap["lan"] || 11;
    
    // 3. Scan for existing entry for today OR find the first truly blank row
    var matchRow = -1;
    var firstEmptyRow = -1;
    var maxSr = 0;
    
    for (var i = headerRowIdx + 1; i < values.length; i++) {
      var rowVal = values[i];
      var rowSr = parseInt(rowVal[colSr - 1], 10);
      if (!isNaN(rowSr) && rowSr > maxSr) maxSr = rowSr;
      
      var rowDate = rowVal[colDate - 1] ? rowVal[colDate - 1].toString().trim() : "";
      var rowHost = rowVal[colHost - 1] ? rowVal[colHost - 1].toString().trim() : "";
      
      // Check for match on today's date
      var isDateMatch = (rowDate === todayStr || rowDate === todayShort || rowDate.indexOf(todayStr.slice(0, 5)) !== -1);
      if (rowHost.toLowerCase() === targetHost.toLowerCase() && isDateMatch) {
        matchRow = i + 1; // 1-based index
        break;
      }
      
      // Track the first row where Host Name is empty
      if (rowHost === "" && firstEmptyRow === -1) {
        firstEmptyRow = i + 1;
      }
    }
    
    // 4. Update existing row OR write to the first empty row
    if (matchRow !== -1) {
      sheet.getRange(matchRow, colWanPe).setValue(data.wan_pe);
      sheet.getRange(matchRow, colWanCpe).setValue(data.wan_cpe);
      sheet.getRange(matchRow, colLan).setValue(data.lan_ip);
      
      // Force write to spreadsheet immediately
      SpreadsheetApp.flush();
      
      return ContentService.createTextOutput(JSON.stringify({
        status: "success",
        message: "Updated existing Row #" + matchRow + " for '" + targetHost + "' (IPs updated)."
      })).setMimeType(ContentService.MimeType.JSON);
    } else {
      var targetRow = (firstEmptyRow !== -1) ? firstEmptyRow : (values.length + 1);
      var nextSr = maxSr > 0 ? (maxSr + 1) : (targetRow - headerRowIdx);
      
      // Write directly to the specific row's cells
      sheet.getRange(targetRow, colSr).setValue(nextSr);
      sheet.getRange(targetRow, colDate).setValue(todayShort); // Format as 02/11/26 matching your sheet
      if (data.dist)   sheet.getRange(targetRow, colDist).setValue(data.dist);
      if (data.tehsil) sheet.getRange(targetRow, colTehsil).setValue(data.tehsil);
      sheet.getRange(targetRow, colHost).setValue(targetHost);
      sheet.getRange(targetRow, colWanPe).setValue(data.wan_pe || "");
      sheet.getRange(targetRow, colWanCpe).setValue(data.wan_cpe || "");
      sheet.getRange(targetRow, colLan).setValue(data.lan_ip || "");
      
      // Force write to spreadsheet immediately
      SpreadsheetApp.flush();
      
      return ContentService.createTextOutput(JSON.stringify({
        status: "success",
        message: "Added data in Row #" + targetRow + " for '" + targetHost + "' on " + sheet.getName()
      })).setMimeType(ContentService.MimeType.JSON);
    }
  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({
      status: "error",
      message: err.toString()
    })).setMimeType(ContentService.MimeType.JSON);
  }
}
