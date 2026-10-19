const PHANTOM_API_BASE_URL = 'https://api.phantombuster.com/api/v2';
const RESULT_FILE_BASE_URL = 'https://phantombuster.s3.amazonaws.com';
const CUSTOMER_INFO_SHEET = 'customer_info';
const AUTOMATION_STATE_SHEET = '_automation_state';
const AUTOMATION_LOG_SHEET = '_automation_log';
const RAW_RESULT_NAME = 'result.csv';
const PIPELINE_HEADERS = [
  'content_summary',
  'processing_status',
  'processing_error'
];
const REQUIRED_PROPERTIES = [
  'PHANTOMBUSTER_API_KEY',
  'PHANTOMBUSTER_AGENT_ID',
  'GEMINI_API_KEY',
  'GEMINI_MODEL',
  'TIMEZONE',
  'WEEK_START_DAY',
  'SCHEDULE_DAY',
  'SCHEDULE_TIME',
  'ENABLE_MANUAL_TEST_MENU'
];
const STATE_KEYS = {
  ACTIVE_RUN: 'active_phantom_run',
  LAST_WEEK: 'last_imported_week'
};
const WORKER_TRIGGER_HANDLERS = [
  'retryIncompleteWork',
  'summarizeImportedWeek'
];

function onOpen() {
  const ui = SpreadsheetApp.getUi();
  if (getProperty('ENABLE_MANUAL_TEST_MENU') === 'true') {
    ui.createMenu('LinkedIn Automation (Testing)')
      .addItem('Phantom Data Scraping', 'runPhantomDataScraping')
      .addItem('Content Summarization', 'runContentSummarization')
      .addToUi();
  }
}

function runPhantomDataScraping() {
  schedulePhantomRun();
  pollPhantomRun();
}

function schedulePhantomRun() {
  return withScriptLock_(schedulePhantomRun_);
}

function schedulePhantomRun_() {
  automationLog_('INFO', 'PHANTOM_LAUNCH', 'Preparing PhantomBuster launch.');
  const config = getConfig_();
  const period = getClosedReportingPeriod_(
    new Date(),
    config.timezone,
    config.weekStartDay
  );
  const existing = readState_(STATE_KEYS.ACTIVE_RUN);
  if (existing && existing.status !== 'imported' && existing.status !== 'failed') {
    ensureWorkerTriggers_();
    automationLog_(
      'INFO',
      'PHANTOM_LAUNCH',
      'Reusing active container ' + existing.containerId + '.'
    );
    return existing;
  }

  const sheet = SpreadsheetApp.getActiveSpreadsheet();
  const customerRows = readCustomerInfo_(sheet);
  if (!customerRows.length) {
    throw new Error('customer_info contains no valid profile rows.');
  }

  const payload = {
    id: config.agentId,
    bonusArgument: {
      spreadsheetUrl: sheet.getUrl(),
      columnName: 'linkedin_profile_url',
      activitiesToScrape: ['Post'],
      onlyRetrieveActivitiesAfterDate: true,
      dateAfter: formatPhantomDate_(period.start),
      numberOfLinesPerLaunch: customerRows.length,
      numberMaxOfPosts: 20,
      csvName: 'result'
    }
  };
  const response = phantomRequest_(
    '/agents/launch',
    'post',
    config.apiKey,
    payload
  );
  const containerId = extractContainerId_(response);
  if (!containerId) {
    throw new Error('Phantom launch response did not include a container ID.');
  }

  const run = {
    agentId: config.agentId,
    containerId: String(containerId),
    weekKey: period.key,
    weekStart: period.start,
    weekEnd: period.end,
    status: 'launched',
    launchedAt: new Date().toISOString(),
    pollAttempts: 0
  };
  writeState_(STATE_KEYS.ACTIVE_RUN, run);
  ensureWorkerTriggers_();
  automationLog_(
    'INFO',
    'PHANTOM_LAUNCH',
    'Launched container ' + run.containerId + '.'
  );
  return run;
}

function pollPhantomRun() {
  return withScriptLock_(pollPhantomRun_);
}

function pollPhantomRun_() {
  automationLog_('INFO', 'PHANTOM_POLL', 'Checking Phantom container status.');
  const config = getConfig_();
  const run = readState_(STATE_KEYS.ACTIVE_RUN);
  if (!run) {
    throw new Error('No active Phantom launch is stored.');
  }
  if (run.status === 'imported') {
    automationLog_('INFO', 'PHANTOM_POLL', 'Container was already imported.');
    return run;
  }

  const containers = phantomRequest_(
    '/containers/fetch-all?agentId=' + encodeURIComponent(config.agentId),
    'get',
    config.apiKey
  );
  const container = findContainer_(containers, run.containerId);
  if (!container) {
    run.pollAttempts = Number(run.pollAttempts || 0) + 1;
    writeState_(STATE_KEYS.ACTIVE_RUN, run);
    automationLog_('INFO', 'PHANTOM_POLL', 'Container is not visible yet.');
    return run;
  }

  const status = String(
    container.status || container.state || container.containerStatus || ''
  ).toLowerCase();
  run.pollAttempts = Number(run.pollAttempts || 0) + 1;
  run.lastStatus = status;
  automationLog_(
    'INFO',
    'PHANTOM_POLL',
    'Container ' + run.containerId + ' status: ' + status + '.'
  );
  if (status === 'launch error' || status === 'launch_error' ||
      status === 'error' || status === 'failed') {
    run.status = 'failed';
    run.error = String(container.error || container.message || status);
    writeState_(STATE_KEYS.ACTIVE_RUN, run);
    removeWorkerTriggers_();
    throw new Error('Phantom launch failed: ' + run.error);
  }
  if (status !== 'finished' && status !== 'done' && status !== 'completed') {
    writeState_(STATE_KEYS.ACTIVE_RUN, run);
    return run;
  }

  run.status = 'finished';
  writeState_(STATE_KEYS.ACTIVE_RUN, run);
  const imported = importAccumulatedResult_(run, config);
  run.status = 'imported';
  run.importedRows = imported.importedRows;
  run.skippedRows = imported.skippedRows;
  run.importedAt = new Date().toISOString();
  writeState_(STATE_KEYS.ACTIVE_RUN, run);
  writeState_(STATE_KEYS.LAST_WEEK, {
    weekKey: run.weekKey,
    weekStart: run.weekStart,
    weekEnd: run.weekEnd,
    sheetName: imported.sheetName,
    importedAt: run.importedAt
  });
  automationLog_(
    'INFO',
    'PHANTOM_IMPORT',
    'Imported ' + imported.importedRows + ' new row(s); skipped ' +
      imported.skippedRows + '.'
  );
  return run;
}

function retryIncompleteWork() {
  withScriptLock_(function() {
    const run = readState_(STATE_KEYS.ACTIVE_RUN);
    if (run && run.status !== 'imported' && run.status !== 'failed') {
      pollPhantomRun_();
      return;
    }
    const lastWeek = readState_(STATE_KEYS.LAST_WEEK);
    if (lastWeek && lastWeek.weekKey) {
      const imported = importAccumulatedResult_(
        {
          weekKey: lastWeek.weekKey,
          weekStart: lastWeek.weekStart,
          weekEnd: lastWeek.weekEnd
        },
        getConfig_()
      );
      writeState_(STATE_KEYS.LAST_WEEK, {
        weekKey: lastWeek.weekKey,
        weekStart: lastWeek.weekStart,
        weekEnd: lastWeek.weekEnd,
        sheetName: imported.sheetName,
        importedAt: new Date().toISOString()
      });
    }
  });
}

function configureTriggers() {
  const config = getConfig_();
  const time = parseScheduleTime_(config.scheduleTime);
  const day = dayOfWeek_(config.scheduleDay);
  ScriptApp.getProjectTriggers().forEach(function(trigger) {
    const handler = trigger.getHandlerFunction();
    if ([
      'schedulePhantomRun',
      'pollPhantomRun'
    ].concat(WORKER_TRIGGER_HANDLERS).indexOf(handler) !== -1) {
      ScriptApp.deleteTrigger(trigger);
    }
  });
  ScriptApp.newTrigger('schedulePhantomRun')
    .timeBased()
    .onWeekDay(day)
    .atHour(time.hour)
    .nearMinute(time.minute)
    .inTimezone(config.timezone)
    .create();
}

function ensureWorkerTriggers_() {
  const installed = {};
  ScriptApp.getProjectTriggers().forEach(function(trigger) {
    installed[trigger.getHandlerFunction()] = true;
  });
  if (!installed.retryIncompleteWork) {
    ScriptApp.newTrigger('retryIncompleteWork')
      .timeBased()
      .everyHours(1)
      .create();
  }
  if (!installed.summarizeImportedWeek) {
    ScriptApp.newTrigger('summarizeImportedWeek')
      .timeBased()
      .everyHours(1)
      .create();
  }
}

function removeWorkerTriggers_() {
  ScriptApp.getProjectTriggers().forEach(function(trigger) {
    if (WORKER_TRIGGER_HANDLERS.indexOf(trigger.getHandlerFunction()) !== -1) {
      ScriptApp.deleteTrigger(trigger);
    }
  });
}

function importAccumulatedResult_(run, config) {
  automationLog_('INFO', 'PHANTOM_IMPORT', 'Fetching accumulated result metadata.');
  const metadata = phantomRequest_(
    '/agents/fetch?id=' + encodeURIComponent(config.agentId),
    'get',
    config.apiKey
  );
  const orgFolder = String(metadata.orgS3Folder || '').trim();
  const s3Folder = String(metadata.s3Folder || '').trim();
  if (!orgFolder || !s3Folder) {
    throw new Error('Phantom result metadata did not include storage folders.');
  }
  const url = RESULT_FILE_BASE_URL + '/' +
    encodeURIComponent(orgFolder) + '/' +
    encodeURIComponent(s3Folder) + '/' + RAW_RESULT_NAME;
  const response = UrlFetchApp.fetch(url, {muteHttpExceptions: true});
  const status = response.getResponseCode();
  if (status < 200 || status >= 300) {
    throw new Error('Phantom CSV download failed with HTTP ' + status + '.');
  }
  const values = Utilities.parseCsv(response.getContentText());
  if (!values.length) {
    throw new Error('Phantom CSV was empty.');
  }
  const headers = values[0].map(function(value) {
    return String(value).trim();
  });
  if (!headers.length || headers.every(function(value) { return !value; })) {
    throw new Error('Phantom CSV did not contain headers.');
  }
  const rows = values.slice(1).filter(function(row) {
    return row.some(function(value) { return String(value).trim() !== ''; });
  });
  const sheet = SpreadsheetApp.getActiveSpreadsheet();
  const storedStart = normalizePeriodDate_(run.weekStart);
  const storedEnd = normalizePeriodDate_(run.weekEnd);
  const period = storedStart && storedEnd
    ? {
        start: storedStart,
        end: storedEnd,
        key: run.weekKey || storedStart + '_' + storedEnd
      }
    : getClosedReportingPeriod_(
        new Date(),
        config.timezone,
        config.weekStartDay
      );
  run.weekStart = period.start;
  run.weekEnd = period.end;
  run.weekKey = period.key;
  const outputSheet = getOrCreateWeeklySheet_(
    sheet,
    period,
    headers.concat(PIPELINE_HEADERS)
  );
  automationLog_(
    'INFO',
    'PHANTOM_IMPORT',
    'Parsed ' + rows.length + ' accumulated CSV row(s).'
  );
  const existingKeys = readImportedKeys_(sheet);
  const seen = {};
  const customerMap = readCustomerMap_(sheet);
  const newRows = [];
  let skippedRows = 0;
  let skippedInvalidDate = 0;
  let skippedOutsidePeriod = 0;
  let skippedDuplicate = 0;

  rows.forEach(function(row) {
    const item = rowToObject_(headers, row);
    const postDate = selectCsvDate_(item);
    if (!postDate) {
      skippedInvalidDate++;
      skippedRows++;
      return;
    }
    if (!isDateInPeriod_(
        postDate,
        period.start,
        period.end,
        config.timezone
      )) {
      if (isNaN(new Date(postDate).getTime())) skippedInvalidDate++;
      else skippedOutsidePeriod++;
      skippedRows++;
      return;
    }
    const profile = normalizeProfileUrl_(
      item.profileUrl || item.authorUrl || ''
    );
    const customer = customerMap[profile] || '';
    const key = stablePostKey_(item, profile);
    if (!key || seen[key] || existingKeys[key]) {
      skippedDuplicate++;
      skippedRows++;
      return;
    }
    seen[key] = true;
    const normalizedRow = headers.map(function(header, index) {
      return row[index] === undefined ? '' : row[index];
    });
    newRows.push(normalizedRow.concat(['', 'pending', '']));
  });

  if (newRows.length) {
    outputSheet.getRange(
      outputSheet.getLastRow() + 1,
      1,
      newRows.length,
      newRows[0].length
    ).setValues(newRows);
    appendImportedKeys_(sheet, Object.keys(seen));
  }
  automationLog_(
    'INFO',
    'PHANTOM_IMPORT',
    'Skipped rows: ' + skippedInvalidDate + ' invalid date, ' +
      skippedOutsidePeriod + ' outside period, ' + skippedDuplicate +
      ' duplicate or missing key.'
  );
  return {
    sheetName: outputSheet.getName(),
    importedRows: newRows.length,
    skippedRows: skippedRows
  };
}

function readCustomerInfo_(spreadsheet) {
  const sheet = spreadsheet.getSheetByName(CUSTOMER_INFO_SHEET);
  if (!sheet) {
    throw new Error('Missing required sheet: ' + CUSTOMER_INFO_SHEET);
  }
  const rows = sheet.getDataRange().getValues();
  if (rows.length < 2) return [];
  const headers = rows[0].map(function(value) { return String(value).trim(); });
  const nameIndex = headers.indexOf('customer_name');
  const urlIndex = headers.indexOf('linkedin_profile_url');
  if (nameIndex === -1 || urlIndex === -1) {
    throw new Error(
      'customer_info must contain customer_name and linkedin_profile_url.'
    );
  }
  return rows.slice(1).reduce(function(result, row) {
    const name = String(row[nameIndex] || '').trim();
    const url = normalizeProfileUrl_(row[urlIndex]);
    if (name && url && !result.some(function(item) {
      return item.linkedin_profile_url === url;
    })) {
      result.push({customer_name: name, linkedin_profile_url: url});
    }
    return result;
  }, []);
}

function readCustomerMap_(spreadsheet) {
  const map = {};
  readCustomerInfo_(spreadsheet).forEach(function(row) {
    map[row.linkedin_profile_url] = row.customer_name;
  });
  return map;
}

function getOrCreateWeeklySheet_(spreadsheet, period, headers) {
  const name = formatWeeklySheetName_(period.start, period.end);
  let sheet = spreadsheet.getSheetByName(name);
  if (!sheet) sheet = spreadsheet.insertSheet(name);
  if (sheet.getLastRow() === 0) sheet.getRange(1, 1, 1, headers.length)
    .setValues([headers]);
  return sheet;
}

function readImportedKeys_(spreadsheet) {
  const sheet = getStateSheet_(spreadsheet);
  const values = sheet.getDataRange().getValues();
  const keys = {};
  values.slice(1).forEach(function(row) {
    if (row[0] === 'post_key' && row[1]) keys[String(row[1])] = true;
  });
  return keys;
}

function appendImportedKeys_(spreadsheet, keys) {
  if (!keys.length) return;
  const sheet = getStateSheet_(spreadsheet);
  sheet.getRange(sheet.getLastRow() + 1, 1, keys.length, 3).setValues(
    keys.map(function(key) {
      return ['post_key', key, new Date().toISOString()];
    })
  );
}

function getStateSheet_(spreadsheet) {
  let sheet = spreadsheet.getSheetByName(AUTOMATION_STATE_SHEET);
  if (!sheet) {
    sheet = spreadsheet.insertSheet(AUTOMATION_STATE_SHEET);
    sheet.getRange(1, 1, 1, 3).setValues([
      ['record_type', 'record_key', 'record_value']
    ]);
    sheet.hideSheet();
  }
  return sheet;
}

function automationLog_(level, step, message) {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = spreadsheet.getSheetByName(AUTOMATION_LOG_SHEET);
  if (!sheet) {
    sheet = spreadsheet.insertSheet(AUTOMATION_LOG_SHEET);
    sheet.getRange(1, 1, 1, 4).setValues([[
      'timestamp', 'level', 'step', 'message'
    ]]);
  }
  sheet.getRange(sheet.getLastRow() + 1, 1, 1, 4).setValues([[
    new Date(), level, step, message
  ]]);
  spreadsheet.toast(message, step, 5);
}

function rowToObject_(headers, row) {
  const result = {};
  headers.forEach(function(header, index) { result[header] = row[index] || ''; });
  return result;
}

function stablePostKey_(item, profile) {
  const postUrl = String(item.postUrl || item.sharedPostUrl || '').trim();
  if (postUrl) return 'url:' + normalizeUrl_(postUrl);
  const content = String(item.postContent || '').trim().toLowerCase()
    .replace(/\s+/g, ' ');
  const date = String(item.postDate || item.postTimestamp || item.timestamp || '')
    .trim();
  if (!profile || !date || !content) return '';
  return 'fallback:' + profile + '|' + date.slice(0, 10) + '|' + content;
}

function normalizeProfileUrl_(value) {
  let raw = String(value || '').trim();
  if (!raw) return '';
  if (raw.indexOf('://') === -1) raw = 'https://' + raw;
  const parsed = raw.match(/^https?:\/\/([^/?#]+)([^?#]*)/i);
  if (!parsed || !/^(www\.)?linkedin\.com$/i.test(parsed[1])) return '';
  let path = parsed[2].replace(/\/+$/, '').toLowerCase();
  path = path.replace(/\/posts$/, '');
  return 'https://www.linkedin.com' + path;
}

function normalizeUrl_(value) {
  return String(value).trim().replace(/[?#].*$/, '').replace(/\/+$/, '');
}

function selectCsvDate_(item) {
  return String(item.postDate || item.postTimestamp || item.timestamp || '')
    .trim();
}

function isDateInPeriod_(value, start, end, timezone) {
  const date = new Date(value);
  if (isNaN(date.getTime())) return false;
  const formatted = Utilities.formatDate(date, timezone, 'yyyy-MM-dd');
  return formatted >= start && formatted <= end;
}

function normalizePeriodDate_(value) {
  if (value instanceof Date && !isNaN(value.getTime())) {
    const formatted = Utilities.formatDate(value, 'UTC', 'yyyy-MM-dd');
    return formatted.indexOf('1970-') === 0 ? '' : formatted;
  }
  const text = String(value || '').trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) {
    return text.indexOf('1970-') === 0 ? '' : text;
  }
  const date = new Date(text);
  if (isNaN(date.getTime())) return '';
  const formatted = Utilities.formatDate(date, 'UTC', 'yyyy-MM-dd');
  return formatted.indexOf('1970-') === 0 ? '' : formatted;
}

function getClosedReportingPeriod_(now, timezone, weekStartDay) {
  const local = new Date(Utilities.formatDate(now, timezone, 'yyyy-MM-dd HH:mm:ss'));
  const startDay = reportingDayIndex_(weekStartDay);
  const currentDay = local.getDay();
  const daysSinceStart = (currentDay - startDay + 7) % 7;
  const currentStart = new Date(local);
  currentStart.setDate(local.getDate() - daysSinceStart);
  currentStart.setHours(0, 0, 0, 0);
  const end = new Date(currentStart);
  end.setDate(currentStart.getDate() - 1);
  const start = new Date(end);
  start.setDate(end.getDate() - 6);
  const startText = Utilities.formatDate(start, timezone, 'yyyy-MM-dd');
  const endText = Utilities.formatDate(end, timezone, 'yyyy-MM-dd');
  return {start: startText, end: endText, key: startText + '_' + endText};
}

function reportingDayIndex_(value) {
  const indexes = {
    SUNDAY: 0,
    MONDAY: 1,
    TUESDAY: 2,
    WEDNESDAY: 3,
    THURSDAY: 4,
    FRIDAY: 5,
    SATURDAY: 6
  };
  const normalized = String(value || '').toUpperCase();
  if (indexes[normalized] === undefined) {
    throw new Error('Invalid reporting weekday: ' + value);
  }
  return indexes[normalized];
}

function formatWeeklySheetName_(start, end) {
  const timezone = getProperty('TIMEZONE') || 'UTC';
  const startText = normalizePeriodDate_(start);
  const endText = normalizePeriodDate_(end);
  if (!startText || !endText) {
    throw new Error('Reporting period contains an invalid date.');
  }
  const startDate = new Date(startText + 'T00:00:00');
  const endDate = new Date(endText + 'T00:00:00');
  return Utilities.formatDate(startDate, timezone, 'dd') + ' - ' +
    Utilities.formatDate(endDate, timezone, 'dd MMM yyyy');
}

function formatPhantomDate_(isoDate) {
  const parts = isoDate.split('-');
  return parts[1] + '-' + parts[2] + '-' + parts[0];
}

function phantomRequest_(path, method, apiKey, payload) {
  const options = {
    method: method,
    contentType: 'application/json',
    headers: {'x-phantombuster-key': apiKey},
    muteHttpExceptions: true
  };
  if (payload !== undefined) options.payload = JSON.stringify(payload);
  const response = UrlFetchApp.fetch(PHANTOM_API_BASE_URL + path, options);
  const status = response.getResponseCode();
  const body = response.getContentText();
  if (status < 200 || status >= 300) {
    throw new Error('Phantom API request failed with HTTP ' + status + '.');
  }
  try {
    return body ? JSON.parse(body) : {};
  } catch (error) {
    throw new Error('Phantom API returned invalid JSON.');
  }
}

function extractContainerId_(response) {
  return response.containerId || response.container_id || response.id ||
    (response.container && (response.container.id || response.container.containerId)) ||
    (response.data && (
      response.data.containerId ||
      response.data.container_id ||
      response.data.id
    ));
}

function findContainer_(payload, id) {
  const containers = Array.isArray(payload)
    ? payload
    : (payload.containers || payload.data || []);
  return containers.filter(function(item) {
    return String(item.id || item.containerId || '') === String(id);
  })[0] || null;
}

function getConfig_() {
  const properties = PropertiesService.getScriptProperties().getProperties();
  REQUIRED_PROPERTIES.forEach(function(name) {
    if (name !== 'ENABLE_MANUAL_TEST_MENU' && !String(properties[name] || '').trim()) {
      throw new Error('Missing Script Property: ' + name);
    }
  });
  return {
    apiKey: properties.PHANTOMBUSTER_API_KEY,
    agentId: properties.PHANTOMBUSTER_AGENT_ID,
    timezone: properties.TIMEZONE,
    weekStartDay: properties.WEEK_START_DAY,
    scheduleDay: properties.SCHEDULE_DAY,
    scheduleTime: properties.SCHEDULE_TIME
  };
}

function getProperty(name) {
  return PropertiesService.getScriptProperties().getProperty(name) || '';
}

function readState_(key) {
  const value = PropertiesService.getScriptProperties().getProperty(key);
  return value ? JSON.parse(value) : null;
}

function writeState_(key, value) {
  PropertiesService.getScriptProperties().setProperty(key, JSON.stringify(value));
}

function withScriptLock_(callback) {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) {
    throw new Error('Another automation run is already in progress.');
  }
  try {
    return callback();
  } finally {
    lock.releaseLock();
  }
}

function parseScheduleTime_(value) {
  const match = String(value).match(/^([01]\d|2[0-3]):([0-5]\d)$/);
  if (!match) throw new Error('SCHEDULE_TIME must use HH:mm format.');
  return {hour: Number(match[1]), minute: Number(match[2])};
}

function dayOfWeek_(value) {
  const names = {
    SUNDAY: ScriptApp.WeekDay.SUNDAY,
    MONDAY: ScriptApp.WeekDay.MONDAY,
    TUESDAY: ScriptApp.WeekDay.TUESDAY,
    WEDNESDAY: ScriptApp.WeekDay.WEDNESDAY,
    THURSDAY: ScriptApp.WeekDay.THURSDAY,
    FRIDAY: ScriptApp.WeekDay.FRIDAY,
    SATURDAY: ScriptApp.WeekDay.SATURDAY
  };
  const normalized = String(value || '').toUpperCase();
  if (!names[normalized]) throw new Error('Invalid weekday: ' + value);
  return names[normalized];
}
