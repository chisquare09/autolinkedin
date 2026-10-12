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
    .addItem('Weekly Summarize', 'runWeeklyProcessing')
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

    const ui = SpreadsheetApp.getUi();
    const startPrompt = ui.prompt(
      'Weekly Summarize',
      'Enter the start date (YYYY-MM-DD):',
      ui.ButtonSet.OK_CANCEL
    );
    if (startPrompt.getSelectedButton() !== ui.Button.OK) {
      return;
    }

    const endPrompt = ui.prompt(
      'Weekly Summarize',
      'Enter the end date (YYYY-MM-DD):',
      ui.ButtonSet.OK_CANCEL
    );
    if (endPrompt.getSelectedButton() !== ui.Button.OK) {
      return;
    }

    const startDate = startPrompt.getResponseText().trim();
    const endDate = endPrompt.getResponseText().trim();
    if (!isIsoDate(startDate) || !isIsoDate(endDate)) {
      throw new Error('Dates must use YYYY-MM-DD format.');
    }
    if (startDate > endDate) {
      throw new Error('Start date must be on or before end date.');
    }

    const response = UrlFetchApp.fetch(SUMMARIZATION_FUNCTION_URL, {
      method: 'post',
      contentType: 'application/json',
      headers: {
        Authorization: 'Bearer ' + token
      },
      payload: JSON.stringify({
        action: 'process_week',
        start_date: startDate,
        end_date: endDate
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

    let result;
    try {
      result = JSON.parse(body);
    } catch (error) {
      showMessage('Weekly processing completed:\n\n' + body);
      return;
    }

    if (result.processing_errors && result.processing_errors.length > 0) {
      showMessage(
        'Weekly processing completed with coverage warnings:\n\n' + body
      );
      return;
    }

    showMessage('Weekly processing completed:\n\n' + body);
  } finally {
    lock.releaseLock();
  }
}

function isIsoDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return false;
  }

  const parts = value.split('-').map(Number);
  const parsed = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
  return parsed.getUTCFullYear() === parts[0]
    && parsed.getUTCMonth() === parts[1] - 1
    && parsed.getUTCDate() === parts[2];
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
