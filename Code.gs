/**
 * Hệ thống Quản lý Tiền ăn trưa - BSV Web App
 * Backend: Code.gs (Bản sửa lỗi không can thiệp vào sheet Report khi thêm hóa đơn mới)
 */

function doGet(e) {
  // Giả sử bạn trả về một file HTML tên là 'index'
  return HtmlService.createHtmlOutputFromFile('index')
      .setTitle('Ứng dụng của bạn')
      .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL)
      .addMetaTag('viewport', 'width=device-width, initial-scale=1'); // Dòng này bắt buộc phải có để nhận diện Mobile
}

/**
 * Hàm tìm dòng cuối cùng thực sự chứa dữ liệu (Bỏ qua các dòng trống chứa Checkbox)
 * @param {Sheet} sheet Đối tượng Sheet cần tìm
 * @param {number} colIndex Chỉ số cột làm căn cứ đối chiếu (1-based)
 */
function getLastRowWithData(sheet, colIndex) {
  var lastRow = sheet.getLastRow();
  if (lastRow === 0) return 0;
  var values = sheet.getRange(1, colIndex, lastRow, 1).getValues();
  for (var i = values.length - 1; i >= 0; i--) {
    if (values[i][0] && values[i][0].toString().trim() !== "") {
      return i + 1; // Trả về chỉ số dòng thực tế chứa dữ liệu (1-based)
    }
  }
  return 1;
}

/**
 * Hàm tự động định vị cấu trúc bảng của sheet Report
 */
function getSheetStructure(data) {
  var result = {
    headerRowIndex: 0,
    nameColIndex: 1,      // Mặc định Cột B
    totalDebtColIndex: 0  // Mặc định Cột A
  };
  
  for (var i = 0; i < data.length; i++) {
    for (var j = 0; j < data[i].length; j++) {
      var cellVal = data[i][j].toString().trim();
      if (cellVal === "Người tham gia") {
        result.headerRowIndex = i;
        result.nameColIndex = j;
      }
      if (cellVal === "Tổng tiền chưa trả") {
        result.totalDebtColIndex = j;
      }
    }
  }
  return result;
}

/**
 * Lấy danh sách thành viên kèm theo số nợ tương ứng từ Cột A của sheet Report
 */
function getMembers() {
  try {
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var sheet = ss.getSheetByName("Report");
    if (!sheet) return [];
    
    var data = sheet.getDataRange().getValues();
    var structure = getSheetStructure(data);
    
    var memberList = [];
    for (var i = structure.headerRowIndex + 1; i < data.length; i++) {
      var name = data[i][structure.nameColIndex].toString().trim();
      if (name && name !== "Người tham gia" && name.indexOf("Tổng") === -1) {
        var debt = parseFloat(data[i][structure.totalDebtColIndex]) || 0;
        memberList.push({
          name: name,
          debt: debt
        });
      }
    }
    return memberList;
  } catch (e) {
    return [];
  }
}

/**
 * Bóc tách số tiền thông minh từ chuỗi tiêu đề đa dòng xuống hàng
 */
function extractAmountFromHeader(headerStr) {
  if (!headerStr) return 0;
  var str = headerStr.toString().trim();
  var segments = str.split(/[\n\s]+/);
  
  for (var i = segments.length - 1; i >= 0; i--) {
    var cleanSeg = segments[i].replace(/,/g, '').replace(/\./g, '').trim();
    var parsed = parseFloat(cleanSeg);
    if (!isNaN(parsed) && parsed > 0) {
      return parsed;
    }
  }
  return 0;
}

/**
 * Tìm kiếm hàng tương ứng của món ăn trong sheet List thông minh (Chống lệch dòng)
 */
function getMatchingListRowIndex(reportHeader, listData, reportColIndex) {
  var directRowIndex = reportColIndex - 1;
  if (directRowIndex > 0 && directRowIndex < listData.length) {
    var dishName = listData[directRowIndex][1].toString().toLowerCase().replace(/\s/g, '');
    var cleanHeader = reportHeader.toString().toLowerCase().replace(/\s/g, '');
    if (cleanHeader.indexOf(dishName) !== -1) {
      return directRowIndex;
    }
  }
  
  var cleanHeader = reportHeader.toString().toLowerCase().replace(/\s/g, '');
  for (var r = 1; r < listData.length; r++) {
    var dishName = listData[r][1].toString().toLowerCase().replace(/\s/g, '');
    if (dishName && cleanHeader.indexOf(dishName) !== -1) {
      return r;
    }
  }
  return directRowIndex;
}

/**
 * Đối soát chéo thông minh giữa sheet Report và List
 */
function getMemberDebtDetails(memberName) {
  try {
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var reportSheet = ss.getSheetByName("Report");
    var listSheet = ss.getSheetByName("List");
    
    if (!reportSheet || !listSheet) return null;
    
    var reportData = reportSheet.getDataRange().getValues();
    var listData = listSheet.getDataRange().getValues();
    
    var reportStructure = getSheetStructure(reportData);
    var reportHeaders = reportData[reportStructure.headerRowIndex];
    
    // Tìm dòng dữ liệu của thành viên trên sheet "Report" (Cột B)
    var reportMemberRow = null;
    for (var i = reportStructure.headerRowIndex + 1; i < reportData.length; i++) {
      if (reportData[i][reportStructure.nameColIndex] && reportData[i][reportStructure.nameColIndex].toString().trim() === memberName.trim()) {
        reportMemberRow = reportData[i];
        break;
      }
    }
    if (!reportMemberRow) return null;
    
    var totalDebt = parseFloat(reportMemberRow[reportStructure.totalDebtColIndex]) || 0;
    
    // Tìm chỉ số CỘT của thành viên trên sheet "List" (Hàng 1 tiêu đề)
    var listHeaders = listData[0];
    var listMemberColIndex = -1;
    for (var c = 0; c < listHeaders.length; c++) {
      if (listHeaders[c].toString().trim().toLowerCase() === memberName.trim().toLowerCase()) {
        listMemberColIndex = c;
        break;
      }
    }
    
    var unpaidItems = [];
    if (listMemberColIndex === -1) {
      return {
        memberName: memberName,
        totalDebt: totalDebt,
        unpaidItems: []
      };
    }
    
    // Quét chéo: Kiểm tra từng cột nợ chi tiết trên sheet "Report" (Từ cột C - Index 2 trở đi)
    for (var k = 2; k < reportHeaders.length; k++) {
      var headerText = reportHeaders[k].toString().trim();
      if (!headerText || /^[0-9]+$/.test(headerText)) continue;
      
      var reportVal = reportMemberRow[k];
      var isPaidOnReport = (reportVal === true || reportVal === "TRUE" || reportVal === "true");
      
      // Định vị dòng món ăn tương ứng trên sheet "List"
      var listRowIndex = getMatchingListRowIndex(headerText, listData, k);
      
      var hasEatenOnList = false;
      if (listRowIndex > 0 && listRowIndex < listData.length) {
        var listVal = listData[listRowIndex][listMemberColIndex];
        hasEatenOnList = (listVal === true || listVal === "TRUE" || listVal === "true");
      }
      
      if (hasEatenOnList && !isPaidOnReport) {
        var itemAmount = extractAmountFromHeader(headerText);
        unpaidItems.push({
          itemName: headerText.replace(/\n/g, ' '),
          amount: itemAmount,
          colIndex: k
        });
      }
    }
    
    return {
      memberName: memberName,
      totalDebt: totalDebt,
      unpaidItems: unpaidItems
    };
  } catch (e) {
    return null;
  }
}

/**
 * ĐẢM BẢO: Tất cả ô từ C4 trở đi trong Report đều là Checkbox (FALSE).
 * Không đổi ô đã là Checkbox. Bỏ qua ô có công thức (chỉ thêm validation cho ô rỗng).
 * @param {Sheet} reportSheet Đối tượng sheet Report
 */
function ensureReportCheckboxes(reportSheet) {
  try {
    var lastRow = reportSheet.getLastRow();
    if (lastRow < 4) return;

    var lastCol = reportSheet.getLastColumn();
    if (lastCol < 3) return;

    // Lấy giá trị + validation của vùng C4:RowEnd:ColEnd
    var dataRange = reportSheet.getRange(4, 3, lastRow - 3, lastCol - 2);
    var values = dataRange.getValues();
    var validations = dataRange.getDataValidations();

    var cellsToFix = [];

    for (var r = 0; r < values.length; r++) {
      for (var c = 0; c < values[r].length; c++) {
        var val = values[r][c];
        var validation = validations[r][c];

        // Bỏ qua ô trống không có validation gì — không phải ô cần sửa
        if ((val === "" || val === null || val === undefined) && validation === null) {
          continue;
        }

        // Nếu ô đã là checkbox → bỏ qua
        if (validation !== null && validation.getCriteriaType() === SpreadsheetApp.DataValidationCriteria.CHECKBOX) {
          continue;
        }

        // Ô này chưa phải checkbox → cần sửa
        cellsToFix.push({ row: r + 4, col: c + 3, hasFormula: false });
      }
    }

    if (cellsToFix.length === 0) return;

    // Lấy công thức của các ô cần sửa để biết ô nào có công thức
    var fixRows = [];
    cellsToFix.forEach(function(c) { if (fixRows.indexOf(c.row) === -1) fixRows.push(c.row); });
    var formulasRange = reportSheet.getRange(fixRows[0], 3, fixRows.length, lastCol - 2);
    var formulas = formulasRange.getFormulas();

    var hasFormulaSet = [];
    for (var r = 0; r < fixRows.length; r++) {
      var actualRow = fixRows[r];
      for (var c = 0; c < formulas[0].length; c++) {
        var absCol = c + 3;
        var formula = formulas[r][c];
        if (formula && formula.toString().trim() !== "") {
          hasFormulaSet.push(actualRow + "," + absCol);
        }
      }
    }

    var checkboxRule = SpreadsheetApp.newDataValidation().requireCheckbox().build();

    // Group theo hàng để đặt validation theo dải liên tiếp
    var rowGroups = {};
    cellsToFix.forEach(function(cell) {
      var key = cell.row + "," + cell.col;
      if (hasFormulaSet.indexOf(key) !== -1) {
        return; // Bỏ qua ô có công thức
      }
      if (!rowGroups[cell.row]) rowGroups[cell.row] = [];
      rowGroups[cell.row].push(cell.col);
    });

    for (var row in rowGroups) {
      var cols = rowGroups[row].sort(function(a, b) { return a - b; });

      // Tìm các dải liên tiếp để đặt validation
      var segments = [];
      var start = cols[0];
      var end = cols[0];
      for (var i = 1; i < cols.length; i++) {
        if (cols[i] === end + 1) {
          end = cols[i];
        } else {
          segments.push({ start: start, count: end - start + 1 });
          start = cols[i];
          end = cols[i];
        }
      }
      segments.push({ start: start, count: end - start + 1 });

      segments.forEach(function(seg) {
        reportSheet.getRange(parseInt(row), seg.start, 1, seg.count).setDataValidation(checkboxRule);
      });

      cols.forEach(function(col) {
        reportSheet.getRange(parseInt(row), col).setValue(false);
      });
    }
  } catch (e) {
    // Bỏ qua lỗi
  }
}

/**
 * THÊM: Thêm dòng mới cho người lạ vào sheet Report (copy công thức + format từ dòng trên)
 * Chỉ thêm dòng mới, tuyệt đối không sửa thông tin đã có.
 * @param {string} stranger Tên người mới
 * @param {number} reportHeaderRow Chỉ số dòng tiêu đề Report (1-based)
 */
function addStrangerToReport(stranger, reportHeaderRow) {
  try {
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var reportSheet = ss.getSheetByName("Report");
    if (!reportSheet) return;

    var lastRow = reportSheet.getLastRow();
    if (lastRow < reportHeaderRow + 1) lastRow = reportHeaderRow + 1;

    // Chèn dòng sau dòng cuối cùng hiện có
    reportSheet.insertRowAfter(lastRow);

    // Ghi tên người mới vào cột B của dòng vừa chèn
    var newRow = lastRow + 1;
    reportSheet.getRange(newRow, 2).setValue(stranger);

    // Copy công thức + định dạng từ dòng phía trên (cột A có công thức tính nợ)
    reportSheet.getRange(newRow - 1, 1, 1, 1).copyTo(reportSheet.getRange(newRow, 1, 1, 1), {
      formulas: true,
      formats: true
    });
  } catch (e) {
    // Bỏ qua lỗi — Report vẫn dùng được
  }
}

/**
 * ĐÃ SỬA: Thêm hóa đơn ăn mới - TUYỆT ĐỐI không ghi đè hay chỉnh sửa thông tin ĐÃ CÓ trên sheet "Report"
 */
function addBill(billData) {
  try {
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var listSheet = ss.getSheetByName("List");
    var reportSheet = ss.getSheetByName("Report");

    if (!listSheet) {
      return { success: false, message: "Không tìm thấy sheet 'List'." };
    }

    var listData = listSheet.getDataRange().getValues();
    var listHeaders = listData[0];

    // Đọc cấu trúc Report để biết dòng tiêu đề
    var reportStructure = { headerRowIndex: 0 };
    if (reportSheet) {
      var reportData = reportSheet.getDataRange().getValues();
      reportStructure = getSheetStructure(reportData);
    }

    var strangers = billData.strangers || [];

    // 1. Thêm cột người lạ vào sheet List (Nếu có)
    // 2. Thêm dòng người lạ vào sheet Report (copy công thức từ dòng trên)
    strangers.forEach(function(stranger) {
      stranger = stranger.trim();
      if (!stranger) return;

      var alreadyExistsInList = false;
      for (var c = 0; c < listHeaders.length; c++) {
        if (listHeaders[c].toString().trim().toLowerCase() === stranger.toLowerCase()) {
          alreadyExistsInList = true;
          break;
        }
      }

      if (!alreadyExistsInList) {
        // Người lạ được thêm vào cuối sheet (sau cột D "Tiền mỗi người phải trả" và các cột người khác)
        var targetColIndex = listHeaders.length;

        listSheet.insertColumnBefore(targetColIndex + 1);
        listSheet.getRange(1, targetColIndex + 1).setValue(stranger);

        var listLastRowWithData = getLastRowWithData(listSheet, 2);
        if (listLastRowWithData >= 2) {
          var listNewColRange = listSheet.getRange(2, targetColIndex + 1, listLastRowWithData - 1, 1);
          listNewColRange.setDataValidation(SpreadsheetApp.newDataValidation().requireCheckbox().build());
          listNewColRange.setValue(false); // Mặc định không tham gia ăn các bữa cũ
        }

        listHeaders.splice(targetColIndex, 0, stranger);
      }
    });
    
    // Cập nhật lại mảng tiêu đề sau khi thêm người lạ
    listData = listSheet.getDataRange().getValues();
    listHeaders = listData[0];
    
    // 2. Thêm row dữ liệu món ăn mới vào sheet List
    var dateObj = new Date(billData.date);
    var newListRow = [];
    for (var c = 0; c < listHeaders.length; c++) {
      newListRow.push("");
    }
    
    newListRow[0] = dateObj;
    newListRow[1] = billData.dishName;
    newListRow[2] = billData.totalCost;
    
    var allParticipants = (billData.participants || []).concat(strangers);
    
    // Gán trạng thái tích chọn tham gia ăn (TRUE) cho mảng hàng dữ liệu
    allParticipants.forEach(function(participant) {
      participant = participant.trim();
      for (var c = 3; c < listHeaders.length; c++) {
        if (listHeaders[c].toString().trim().toLowerCase() === participant.toLowerCase()) {
          newListRow[c] = true;
          break;
        }
      }
    });
    
    // Định vị dòng trống cuối cùng thực tế trên sheet List (Dựa vào cột B)
    var listLastRowWithData = getLastRowWithData(listSheet, 2);
    var targetListRow = listLastRowWithData + 1;
    
    if (targetListRow > listSheet.getMaxRows()) {
      listSheet.insertRowAfter(listSheet.getMaxRows());
    }
    
    listSheet.getRange(targetListRow, 1, 1, newListRow.length).setValues([newListRow]);
    
    // Đóng khung Checkbox cho dòng mới tạo trên sheet List
    // Cột A=date, B=dish, C=totalCost, D=giá_mỗi_người, E+ = tên người
    var listCheckboxStart = 4; // cột D là index 3 → người bắt đầu từ index 4 (cột E)
    var listColLimit = listHeaders.length;

    if (listColLimit > listCheckboxStart) {
      var listCheckboxRange = listSheet.getRange(targetListRow, listCheckboxStart + 1, 1, listColLimit - listCheckboxStart);
      listCheckboxRange.setDataValidation(SpreadsheetApp.newDataValidation().requireCheckbox().build());
      for (var c = listCheckboxStart; c < listColLimit; c++) {
        var isEating = false;
        var headerLower = listHeaders[c].toString().trim().toLowerCase();
        for (var p = 0; p < allParticipants.length; p++) {
          if (allParticipants[p].toLowerCase() === headerLower) {
            isEating = true;
            break;
          }
        }
        listSheet.getRange(targetListRow, c + 1).setValue(isEating);
      }
    }
    
    // Đồng bộ tức thời để các công thức tự sinh trên sheet Report của bạn tự động tính toán
    SpreadsheetApp.flush();

    if (reportSheet) {
      ensureReportCheckboxes(reportSheet);
    }

    return { success: true };
  } catch (e) {
    return { success: false, message: e.toString() };
  }
}

/**
 * Ghi log lịch sử thanh toán vào sheet Logs & tích TRUE (Đã trả) trên sheet Report
 */
function submitPayment(memberName, selectedItems) {
  try {
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var reportSheet = ss.getSheetByName("Report");
    var logsSheet = ss.getSheetByName("Logs");
    
    if (!reportSheet || !logsSheet) {
      return { success: false, message: "Không tìm thấy sheet 'Report' hoặc 'Logs'." };
    }
    
    var logsHeaders = ["Tên người trả tiền", "Ngày giờ cập nhật", "Các khoản đã trả", "Tổng tiền trong lần trả ấy"];
    var lastRowLogs = logsSheet.getLastRow();
    
    if (lastRowLogs === 0) {
      logsSheet.appendRow(logsHeaders);
    } else {
      var firstCell = logsSheet.getRange(1, 1).getValue().toString().trim();
      if (firstCell !== "Tên người trả tiền") {
        logsSheet.insertRowBefore(1);
        logsSheet.getRange(1, 1, 1, 4).setValues([logsHeaders]);
      }
    }
    
    var reportData = reportSheet.getDataRange().getValues();
    var structure = getSheetStructure(reportData);
    
    var memberRowIndex = -1;
    for (var i = structure.headerRowIndex + 1; i < reportData.length; i++) {
      if (reportData[i][structure.nameColIndex] && reportData[i][structure.nameColIndex].toString().trim() === memberName.trim()) {
        memberRowIndex = i;
        break;
      }
    }
    
    if (memberRowIndex !== -1) {
      selectedItems.forEach(function(item) {
        if (item.colIndex !== undefined) {
          reportSheet.getRange(memberRowIndex + 1, item.colIndex + 1).setValue(true);
        }
      });
    } else {
      return { success: false, message: "Không tìm thấy thành viên '" + memberName + "' trên sheet Report." };
    }
    
    var now = new Date();
    var itemNames = [];
    var totalPaid = 0;
    
    selectedItems.forEach(function(item) {
      itemNames.push(item.itemName);
      totalPaid += parseFloat(item.amount);
    });
    
    logsSheet.appendRow([memberName, now, itemNames.join(", "), totalPaid]);
    SpreadsheetApp.flush();
    
    return { success: true, totalPaid: totalPaid };
  } catch (e) {
    return { success: false, message: e.toString() };
  }
}