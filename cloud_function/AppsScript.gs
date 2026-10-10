/*
 * Google Sheets launcher for the summarization Cloud Run Function.
 *
 * Before use:
 * 1. Set SUMMARIZATION_FUNCTION_URL below to the summarize_function URL.
 * 2. Add WEBHOOK_BEARER_TOKEN in Apps Script:
 *    Project Settings -> Script properties.
 * 3. Keep the phantom_result headers aligned with PhantomBuster's JSON fields.
 */

const SUMMARIZATION_FUNCTION_URL = 'https://YOUR-SUMMARIZATION-FUNCTION-URL';
const RAW_RESULTS_SHEET = 'phantom_result';
const CUSTOMER_INFO_SHEET = 'customer_info';
const WEBHOOK_TOKEN_PROPERTY = 'WEBHOOK_BEARER_TOKEN';

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('LinkedIn Automation')
    .addItem('Run weekly processing', 'runWeeklyProcessing')
    .addToUi();
}

function runWeeklyProcessing() {
  const lock = LockService.getScriptLock();

  if (!lock.tryLock(1000)) {
    throw new Error('Another weekly processing run is already in progress.');
  }

  try {
    const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
    const rawSheet = spreadsheet.getSheetByName(RAW_RESULTS_SHEET);
    const mappingSheet = spreadsheet.getSheetByName(CUSTOMER_INFO_SHEET);

    if (!rawSheet) {
      throw new Error('Missing required sheet: ' + RAW_RESULTS_SHEET);
    }

    if (!mappingSheet) {
      throw new Error('Missing required sheet: ' + CUSTOMER_INFO_SHEET);
    }

    const resultRows = readRowsAsObjects(rawSheet);
    if (resultRows.length === 0) {
      throw new Error('The ' + RAW_RESULTS_SHEET + ' sheet contains no data rows.');
    }

    const token = PropertiesService
      .getScriptProperties()
      .getProperty(WEBHOOK_TOKEN_PROPERTY);

    if (!token) {
      throw new Error(
        'Missing Script Property: ' + WEBHOOK_TOKEN_PROPERTY
      );
    }

    const response = UrlFetchApp.fetch(SUMMARIZATION_FUNCTION_URL, {
      method: 'post',
      contentType: 'application/json',
      headers: {
        Authorization: 'Bearer ' + token
      },
      payload: JSON.stringify({
        action: 'process_week'
      }),
      muteHttpExceptions: true
    });

    const status = response.getResponseCode();
    const body = response.getContentText();

    if (status < 200 || status >= 300) {
      throw new Error(
        'Cloud Run returned HTTP ' + status + ': ' + body
      );
    }

    showMessage('Weekly processing completed:\n\n' + body);
  } finally {
    lock.releaseLock();
  }
}

function readRowsAsObjects(sheet) {
  const values = sheet.getDataRange().getValues();

  if (values.length < 2) {
    return [];
  }

  const headers = values[0].map(function(header) {
    return String(header).trim();
  });

  if (headers.some(function(header) {
    return header === '';
  })) {
    throw new Error('The first row of ' + sheet.getName() + ' contains an empty header.');
  }

  return values
    .slice(1)
    .filter(function(row) {
      return row.some(function(value) {
        return String(value).trim() !== '';
      });
    })
    .map(function(row) {
      const item = {};

      headers.forEach(function(header, index) {
        item[header] = row[index];
      });

      return item;
    });
}

function showMessage(message) {
  try {
    SpreadsheetApp.getUi().alert(message);
  } catch (error) {
    console.log(message);
  }
}
