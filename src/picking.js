/**
 * src/picking.js
 * Plain CommonJS logic layer for the vending-machine "daily picking list" feature.
 */

/**
 * Converts a value to a finite integer, or returns 0.
 * Treat '', null, and undefined as 0.
 * @param {any} v
 * @returns {number}
 */
function num(v) {
  if (v === '' || v === null || v === undefined) {
    return 0;
  }
  const n = Number(v);
  return Number.isFinite(n) ? Math.round(n) : 0;
}

/**
 * Returns a 3-letter weekday name for a JS Date object.
 * @param {Date} date
 * @returns {string} 'Sun'|'Mon'|'Tue'|'Wed'|'Thu'|'Fri'|'Sat'
 */
function weekdayName(date) {
  const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  return days[date.getDay()];
}

/**
 * Excel caps sheet names at 31 chars, so a machine whose real name is longer
 * appears truncated in the report while the route plan holds the full name.
 * Resolves a report-side machine name to its route-plan key: exact match
 * first, then 31-char-prefix match for long plan names.
 * @param {object} machinesInPlan - routePlan.machines
 * @param {string} machineName - machine name as it appears in the report
 * @returns {string|null} the route-plan key, or null if no match
 */
function planKeyFor(machinesInPlan, machineName) {
  if (Object.prototype.hasOwnProperty.call(machinesInPlan, machineName)) {
    return machineName;
  }
  const name = String(machineName);
  if (name.length === 31) {
    for (const key in machinesInPlan) {
      if (key.length > 31 && key.slice(0, 31) === name) {
        return key;
      }
    }
  }
  return null;
}

/**
 * Sums a machine's FINAL restock across its lanes the same way
 * buildPickingList Step F does — in-transit deducted per lane, buffer applied
 * (negative sem-break buffer subtracts, floored at 0, capped at lane size) —
 * so the sidebar % reflects the actual picking-list demand, not the raw report
 * Restock column. Forecast is intentionally omitted (sidebar is a today view).
 * @param {any[][]} rows - the machine's data rows (no header)
 * @param {object} pendingByLane - {laneNo: qty, ...}
 * @param {object} bufferByLane - {laneNo: qty, ...} (mode-resolved; negative for sem break)
 * @returns {{laneSum:number, restockSum:number, pct:number}}
 */
function machineRestockPct(rows, pendingByLane, bufferByLane) {
  pendingByLane = pendingByLane || {};
  bufferByLane = bufferByLane || {};
  let laneSum = 0;
  let restockSum = 0;
  for (const r of rows) {
    const laneNo = String(r[1]);
    const laneSize = num(r[5]);
    const bal = num(r[4]);
    const restock = num(r[6]);
    const actualRestock = Math.max(0, restock - (pendingByLane[laneNo] || 0));
    const bufferQty = actualRestock === 0 ? 0 : Math.min(bufferByLane[laneNo] || 0, bal);
    const space = Math.max(0, laneSize - bal); // free space at report time
    const capped = laneSize > 0 ? Math.min(actualRestock, space) : actualRestock;
    const withBuffer = capped + bufferQty;
    // buffer covers in-transit sales, which free extra space by refill time,
    // so the ceiling is space + buffer (positive buffer only)
    const ceiling = space + Math.max(0, bufferQty);
    const finalRestock = Math.max(0, laneSize > 0 ? Math.min(withBuffer, ceiling) : withBuffer);
    laneSum += laneSize;
    restockSum += finalRestock;
  }
  const pct = laneSum > 0 ? Math.round(restockSum / laneSum * 100) / 100 : 0;
  return { laneSum, restockSum, pct };
}

/**
 * Determines which machines qualify for picking today.
 * @param {any[][]} reportRows
 * @param {object} routePlan
 * @param {Date} date
 * @param {object} pendingByMachine - {machineName: {laneNo: qty, ...}, ...}
 * @param {object} bufferByMachine - {machineName: {laneNo: qty, ...}, ...} (mode-resolved)
 * @returns {object[]}
 */
function machinesToPickToday(reportRows, routePlan, date, pendingByMachine, bufferByMachine) {
  if (!pendingByMachine) pendingByMachine = {};
  if (!bufferByMachine) bufferByMachine = {};
  const machinesInPlan = (routePlan && routePlan.machines) ? routePlan.machines : {};
  const groups = {};

  // Group the data rows (skip header row 0) by machineName (column 0)
  for (let i = 1; i < reportRows.length; i++) {
    const row = reportRows[i];
    if (!row || row.length === 0) continue;
    const machineName = row[0];
    if (machineName === undefined || machineName === null || machineName === '') continue;

    if (!groups[machineName]) {
      groups[machineName] = [];
    }
    groups[machineName].push(row);
  }

  const wd = weekdayName(date);
  const results = [];

  for (const machineName in groups) {
    if (Object.prototype.hasOwnProperty.call(groups, machineName)) {
      // Consider only machines that exist in BOTH reportRows and routePlan.machines
      const planKey = planKeyFor(machinesInPlan, machineName);
      if (!planKey) {
        continue;
      }
      const machinePlan = machinesInPlan[planKey];
      const rows = groups[machineName];

      // Per-lane: in-transit deducted + buffer applied (Step F semantics),
      // so the % matches the machine's actual picking-list demand.
      const { laneSum, restockSum: adjustedRestockSum, pct } =
        machineRestockPct(rows, pendingByMachine[machineName], bufferByMachine[machineName]);

      const scheduleDays = machinePlan.scheduleDays || [];
      const scheduled = scheduleDays.includes(wd);

      // The machine QUALIFIES if scheduled === true OR pct >= 0.25
      if (scheduled || pct >= 0.25) {
        let reason = '';
        if (scheduled) {
          if (scheduleDays.length >= 6) {
            reason = 'daily';
          } else {
            reason = 'scheduled';
          }
        } else {
          reason = '25%';
        }

        results.push({
          machine: machineName,
          team: machinePlan.team || 'UNASSIGNED',
          reason,
          adjustedRestockSum,
          laneSum,
          pct
        });
      }
    }
  }

  // Sort by team: '5530' first, then '1126', then 'UNASSIGNED', then any other alphabetically.
  // Then by machine name A-Z within team.
  results.sort((a, b) => {
    const getTeamPriority = (team) => {
      if (team === '5530') return 1;
      if (team === '1126') return 2;
      if (team === 'UNASSIGNED') return 3;
      return 4;
    };

    const pA = getTeamPriority(a.team);
    const pB = getTeamPriority(b.team);

    if (pA !== pB) {
      return pA - pB;
    }

    if (pA === 4) {
      const teamA = a.team || '';
      const teamB = b.team || '';
      if (teamA !== teamB) {
        return teamA.localeCompare(teamB);
      }
    }

    return a.machine.localeCompare(b.machine);
  });

  return results;
}

/**
 * KI-2 fix: forecastByPid holds machine-level totals (avg qty for that PID
 * across the whole machine); when the same PID occupies N lanes, applying
 * the full total per lane overcounts N×. Splits each PID's qty evenly
 * across the lanes it occupies on this machine.
 * @param {any[][]} reportRows
 * @param {string} machine
 * @param {object} forecastByPid - {pid: avg_qty, ...}
 * @returns {object} - {pid: avg_qty / laneCount, ...}
 */
function splitForecastAcrossLanes(reportRows, machine, forecastByPid) {
  if (!forecastByPid || !Object.keys(forecastByPid).length) return forecastByPid || {};
  const laneCount = {};
  for (let i = 1; i < reportRows.length; i++) {
    const row = reportRows[i];
    if (row && row[0] === machine) {
      const pid = String(row[2]);
      laneCount[pid] = (laneCount[pid] || 0) + 1;
    }
  }
  const out = {};
  for (const pid in forecastByPid) {
    out[pid] = laneCount[pid] > 1 ? forecastByPid[pid] / laneCount[pid] : forecastByPid[pid];
  }
  return out;
}

/**
 * Lists ALL lanes of a machine from the report, unfiltered.
 * Q3 needs the full lane inventory (not the filtered picking rows) for
 * tray-average calculation and "already stocked" candidate marking.
 * @param {any[][]} reportRows
 * @param {string} machine
 * @returns {Array<{laneNo: string, pid: string, laneSize: number}>}
 */
function listMachineLanes(reportRows, machine) {
  const lanes = [];
  for (let i = 1; i < reportRows.length; i++) {
    const row = reportRows[i];
    if (row && row[0] === machine) {
      lanes.push({ laneNo: String(row[1]), pid: String(row[2]), product: String(row[3] || ''), laneSize: num(row[5]) });
    }
  }
  return lanes;
}

/**
 * Q3: flags slow movers among the picking rows and proposes replacement
 * candidates (same tray, same lane size, ranked by global sales).
 *
 * Slow test: machineSales[pid] < thresholdPct/100 × trayAvg, where trayAvg
 * is the mean machineSales of DISTINCT pids of that tray currently stocked
 * anywhere on this machine (a pid spanning several lanes counts once).
 *
 * @param {Array<{laneNo: string, productId: string, lane: number}>} pickRows
 * @param {Array<{laneNo: string, pid: string, laneSize: number}>} machineLanes
 * @param {object} catalog      - {pid: {name, tray, size}}
 * @param {object} machineSales - {pid: count} this machine, 30d window
 * @param {object} globalSales  - {pid: count} all machines, same window
 * @param {number} thresholdPct - e.g. 50 → slow if below half of tray avg
 * @param {number} [topN=3]
 * @returns {object} - {laneNo: {candidates: [{pid, name, sales, inLane}]}}
 */
function suggestReplacements(pickRows, machineLanes, catalog, machineSales, globalSales, thresholdPct, topN) {
  if (!topN) topN = 3;
  if (!catalog || !Object.keys(catalog).length) return {};

  // pid → first lane it occupies on this machine
  const stockedLane = {};
  for (const l of machineLanes) {
    if (!(l.pid in stockedLane)) stockedLane[l.pid] = l.laneNo;
  }

  // tray → mean machineSales over distinct stocked pids of that tray
  const traySums = {};
  for (const pid in stockedLane) {
    const cat = catalog[pid];
    if (!cat) continue;
    if (!traySums[cat.tray]) traySums[cat.tray] = { sum: 0, n: 0 };
    traySums[cat.tray].sum += machineSales[pid] || 0;
    traySums[cat.tray].n += 1;
  }

  const out = {};
  for (const row of pickRows) {
    const pid = String(row.productId || '');
    const cat = catalog[pid];
    if (!cat) continue;
    const t = traySums[cat.tray];
    if (!t || t.n === 0) continue;
    const trayAvg = t.sum / t.n;
    if (trayAvg <= 0) continue;
    if ((machineSales[pid] || 0) >= (thresholdPct / 100) * trayAvg) continue;

    const candidates = [];
    for (const cPid in catalog) {
      if (cPid === pid) continue;
      const c = catalog[cPid];
      if (c.tray !== cat.tray || c.size !== row.lane) continue;
      const sales = globalSales[cPid] || 0;
      if (sales <= 0) continue;
      candidates.push({ pid: cPid, name: c.name, sales, inLane: stockedLane[cPid] || null });
    }
    if (!candidates.length) continue;
    candidates.sort((a, b) => b.sales - a.sales);
    out[String(row.laneNo)] = { candidates: candidates.slice(0, topN) };
  }
  return out;
}

/**
 * Builds the picking list for a single machine.
 * @param {any[][]} reportRows
 * @param {string} machine
 * @param {object} pendingByLane - {laneNo: qty, ...}
 * @param {object} oosByLane - {laneNo: count, ...}
 * @param {object} forecastByPid - {pid: avg_qty, ...}  (pass {} if unavailable)
 * @param {boolean} semBreak - if true, forecast is disabled
 * @param {object} bufferByLane - {laneNo: bufferQty, ...} (pass {} if unavailable)
 * @returns {object}
 */
function buildPickingList(reportRows, machine, pendingByLane, oosByLane, forecastByPid, semBreak, bufferByLane) {
  if (!pendingByLane) pendingByLane = {};
  if (!oosByLane) oosByLane = {};
  if (!forecastByPid) forecastByPid = {};
  if (semBreak === undefined) semBreak = false;
  if (!bufferByLane) bufferByLane = {};

  // Take only data rows whose column 0 === machine
  const machineRows = [];
  for (let i = 1; i < reportRows.length; i++) {
    const row = reportRows[i];
    if (row && row[0] === machine) {
      machineRows.push(row);
    }
  }

  const visibleRows = [];
  const hiddenRows = [];
  let hiddenCount = 0;

  for (const row of machineRows) {
    const restock = num(row[6]); // Restock is col 6
    const laneNo = String(row[1]); // No. column
    const laneInTransit = pendingByLane[laneNo] || 0;
    const actualRestock = Math.max(0, restock - laneInTransit);

    const bal = num(row[4]); // Bal Qty is col 4
    // Step C: rows where num(balQty) >= 10 go to hiddenRows — display-only
    // (renderer can unhide them); they never join rows, so queue/print totals
    // are unaffected
    if (bal >= 10) {
      hiddenCount++;
      hiddenRows.push({
        no: row[1],
        productId: String(row[2]),
        product: row[3] !== undefined && row[3] !== null ? String(row[3]) : '',
        bal,
        lane: num(row[5]),
        restock: actualRestock,
        forecastQty: 0,
        bufferQty: 0,
        outOfStock: false,
        fastMover: false,
        zeroRestock: actualRestock === 0,
        highBal: true,
        laneNo
      });
      continue;
    }

    // Step B: zero-restock lanes stay visible (flagged) but never pick up
    // forecast/buffer additions, so queue and print totals are unaffected
    const zeroRestock = (actualRestock === 0);

    // Step A: out of stock
    const outOfStock = (bal === 0);

    // Step D: fast-mover highlight (oos7 >= 3 in past 7 days)
    const oos7 = oosByLane[laneNo] || 0;
    const fastMover = oos7 >= 3;

    // Step E: forecast qty
    const pid = String(row[2]);
    const forecastQty = (semBreak || zeroRestock) ? 0 : Math.round((forecastByPid[pid] || 0));

    // Step F: buffer qty — covers lead-time sales (pick → refill), so it can
    // never exceed what's left in the lane (bal), and the total load can
    // never exceed the lane's free space (laneSize - bal)
    const laneSize = num(row[5]);
    const space = Math.max(0, laneSize - bal); // free space at report time
    const bufferQty = zeroRestock ? 0 : Math.min(bufferByLane[laneNo] || 0, bal);
    // forecast and positive buffer both cover lead-time sales, which free extra
    // space by refill time, so both ride ABOVE free space: ceiling = space +
    // forecast + positive buffer
    const withExtras = actualRestock + forecastQty + bufferQty;
    const ceiling = space + forecastQty + Math.max(0, bufferQty);
    const finalRestock = Math.max(0, laneSize > 0 ? Math.min(withExtras, ceiling) : withExtras);

    visibleRows.push({
      no: row[1],
      productId: pid,
      product: row[3] !== undefined && row[3] !== null ? String(row[3]) : '',
      bal,
      lane: num(row[5]),
      restock: finalRestock,
      forecastQty,
      bufferQty,
      outOfStock,
      fastMover,
      zeroRestock,
      laneNo
    });
  }

  return {
    machine,
    rows: visibleRows,
    hiddenRows,
    hiddenCount
  };
}

module.exports = {
  num,
  weekdayName,
  planKeyFor,
  machineRestockPct,
  machinesToPickToday,
  buildPickingList,
  splitForecastAcrossLanes,
  listMachineLanes,
  suggestReplacements
};

// Self-check block
if (require.main === module) {
  const assert = require('assert');

  // Verify num(v)
  assert.strictEqual(num(''), 0);
  assert.strictEqual(num('3'), 3);
  assert.strictEqual(num(2.6), 3);
  assert.strictEqual(num(null), 0);
  assert.strictEqual(num(undefined), 0);
  assert.strictEqual(num('abc'), 0);

  // Verify weekdayName
  const dateSat = new Date('2026-06-20T12:00:00'); // Saturday
  assert.strictEqual(weekdayName(dateSat), 'Sat');
  const dateSun = new Date('2026-06-21T12:00:00'); // Sunday
  assert.strictEqual(weekdayName(dateSun), 'Sun');

  // Verify machinesToPickToday
  const mockReport = [
    ['Machine','No.','Product ID','Product Name','Bal Qty','Lane Size','Restock'],
    ['MachA', '1', 'P1', 'Soda', '5', '10', '3'],    // lane=10, restock=3 => pct = 0.3. Not scheduled. Team: 1126
    ['MachB', '1', 'P1', 'Soda', '5', '10', '1'],    // lane=10, restock=1 => pct = 0.1. Daily. Team: 5530
    ['MachC', '1', 'P1', 'Soda', '5', '10', '1'],    // lane=10, restock=1 => pct = 0.1. Not scheduled today. Team: UNASSIGNED
    ['MachD', '1', 'P1', 'Soda', '5', '10', '1'],    // lane=10, restock=1 => pct = 0.1. Scheduled. Team: CustomTeamB
    ['MachE', '1', 'P1', 'Soda', '5', '10', '3'],    // lane=10, restock=3 => pct = 0.3. Not scheduled. Team: CustomTeamA
  ];

  const mockRoutePlan = {
    machines: {
      'MachA': { team: '1126', scheduleDays: [] },
      'MachB': { team: '5530', scheduleDays: ['Sat','Mon','Tue','Wed','Thu','Fri','Sun'] }, // 7 days (>= 6)
      'MachC': { team: 'UNASSIGNED', scheduleDays: ['Mon'] }, // 1 day, today is Sat, not scheduled
      'MachD': { team: 'CustomTeamB', scheduleDays: ['Sat','Wed','Thu'] }, // 3 days, today is Sat, scheduled
      'MachE': { team: 'CustomTeamA', scheduleDays: [] } // not scheduled, but pct >= 0.25 (0.3)
    }
  };

  const results = machinesToPickToday(mockReport, mockRoutePlan, dateSat, {});

  // Expected qualifying machines:
  // - MachB: team 5530, priority 1, reason 'daily'
  // - MachA: team 1126, priority 2, reason '25%'
  // - MachE: team CustomTeamA, priority 4, reason '25%'
  // - MachD: team CustomTeamB, priority 4, reason 'scheduled'
  // MachC is not scheduled today and pct is 0.1 (< 0.25), so NOT returned.
  assert.strictEqual(results.length, 4);

  assert.strictEqual(results[0].machine, 'MachB');
  assert.strictEqual(results[0].team, '5530');
  assert.strictEqual(results[0].reason, 'daily');
  assert.strictEqual(results[0].pct, 0.1);

  assert.strictEqual(results[1].machine, 'MachA');
  assert.strictEqual(results[1].team, '1126');
  assert.strictEqual(results[1].reason, '25%');
  assert.strictEqual(results[1].pct, 0.3);

  assert.strictEqual(results[2].machine, 'MachE');
  assert.strictEqual(results[2].team, 'CustomTeamA');
  assert.strictEqual(results[2].reason, '25%');
  assert.strictEqual(results[2].pct, 0.3);

  assert.strictEqual(results[3].machine, 'MachD');
  assert.strictEqual(results[3].team, 'CustomTeamB');
  assert.strictEqual(results[3].reason, 'scheduled');
  assert.strictEqual(results[3].pct, 0.1);

  // Verify planKeyFor: Excel truncates sheet names to 31 chars, so a long
  // plan name must still match its truncated report-side name
  const longName = 'UKB Bahasa Dan Linguistik M3 Twin';      // 33 chars
  const truncName = longName.slice(0, 31);                   // as it appears in the report
  const planWithLongName = { [longName]: { team: '1126', scheduleDays: [] }, 'MachA': { team: '1126', scheduleDays: [] } };
  assert.strictEqual(planKeyFor(planWithLongName, 'MachA'), 'MachA');
  assert.strictEqual(planKeyFor(planWithLongName, truncName), longName);
  assert.strictEqual(planKeyFor(planWithLongName, 'Unknown Machine'), null);

  const mockReportTrunc = [
    ['Machine','No.','Product ID','Product Name','Bal Qty','Lane Size','Restock'],
    [truncName, '1', 'P1', 'Soda', '5', '10', '3'],          // pct 0.3 → qualifies via 25% rule
  ];
  const truncResults = machinesToPickToday(mockReportTrunc, { machines: planWithLongName }, dateSat, {});
  assert.strictEqual(truncResults.length, 1);
  assert.strictEqual(truncResults[0].machine, truncName);    // report-side name is the identity
  assert.strictEqual(truncResults[0].team, '1126');

  // Verify buildPickingList
  const mockReportList = [
    ['Machine','No.','Product ID','Product Name','Bal Qty','Lane Size','Restock'],
    ['MachX', '1', 'P1', 'A', '5', '10', '0'],   // restock === 0 -> visible but flagged zeroRestock (Step B)
    ['MachX', '2', 'P2', 'B', '11', '10', '2'],  // balQty === 11 (> 10) -> drop (Step C)
    ['MachX', '3', 'P3', 'C', '0', '10', '4'],   // balQty === 0 (<=10, restock>0) -> survive, outOfStock = true
    ['MachX', '4', 'P4', 'D', '5', '10', '3'],   // balQty === 5 (<=10, restock>0) -> survive, outOfStock = false
  ];

  const pickList = buildPickingList(mockReportList, 'MachX', {}, {});
  assert.strictEqual(pickList.machine, 'MachX');
  assert.strictEqual(pickList.hiddenCount, 1);
  assert.strictEqual(pickList.rows.length, 3);
  assert.strictEqual(pickList.hiddenRows.length, 1);
  assert.strictEqual(pickList.hiddenRows[0].productId, 'P2');
  assert.strictEqual(pickList.hiddenRows[0].highBal, true);

  assert.strictEqual(pickList.rows[0].productId, 'P1');
  assert.strictEqual(pickList.rows[0].zeroRestock, true);
  assert.strictEqual(pickList.rows[0].restock, 0);

  assert.strictEqual(pickList.rows[1].productId, 'P3');
  assert.strictEqual(pickList.rows[1].outOfStock, true);
  assert.strictEqual(pickList.rows[1].zeroRestock, false);
  assert.strictEqual(pickList.rows[1].bal, 0);
  assert.strictEqual(pickList.rows[1].restock, 4);

  assert.strictEqual(pickList.rows[2].productId, 'P4');
  assert.strictEqual(pickList.rows[2].outOfStock, false);
  assert.strictEqual(pickList.rows[2].bal, 5);
  assert.strictEqual(pickList.rows[2].restock, 3);

  // zero-restock lane must ignore forecast and buffer (totals unchanged)
  const plZero = buildPickingList(mockReportList, 'MachX', {}, {}, { P1: 6 }, false, { '1': 2 });
  assert.strictEqual(plZero.rows[0].productId, 'P1');
  assert.strictEqual(plZero.rows[0].restock, 0);
  assert.strictEqual(plZero.rows[0].forecastQty, 0);
  assert.strictEqual(plZero.rows[0].bufferQty, 0);

  // buffer is capped by bal (lead-time sales can't exceed what's in the machine)
  const plBuf = buildPickingList(mockReportList, 'MachX', {}, {}, {}, false, { '3': 4, '4': 8 });
  const rOut = plBuf.rows.find(r => r.productId === 'P3');   // bal 0 → buffer 0
  assert.strictEqual(rOut.bufferQty, 0);
  assert.strictEqual(rOut.restock, 4);
  const rCap = plBuf.rows.find(r => r.productId === 'P4');   // bal 5 → buffer 8 capped to 5
  assert.strictEqual(rCap.bufferQty, 5);
  assert.strictEqual(rCap.restock, 8);                       // free space 5 + buffer 5, capped by restock+forecast+buffer = 3+0+5

  // buffer rides ABOVE free space (covers in-transit sales that free room by refill)
  const mockReportLaneCap = [
    ['Machine','No.','Product ID','Product Name','Bal Qty','Lane Size','Restock'],
    ['MachL', '1', 'P1', 'A', '5', '6', '3'],
  ];
  const plLaneCap = buildPickingList(mockReportLaneCap, 'MachL', {}, {}, {}, false, { '1': 5 });
  assert.strictEqual(plLaneCap.rows[0].bufferQty, 5);        // bal 5 allows it
  assert.strictEqual(plLaneCap.rows[0].restock, 6);          // free space 1 + buffer 5

  // negative (sem-break) buffer still reduces restock, floor at 0
  const plNeg = buildPickingList(mockReportLaneCap, 'MachL', {}, {}, {}, false, { '1': -5 });
  assert.strictEqual(plNeg.rows[0].bufferQty, -5);
  assert.strictEqual(plNeg.rows[0].restock, 0);              // 3 - 5 → floored

  // fully in-transit lane counts as zeroRestock too
  const plIT = buildPickingList(mockReportList, 'MachX', { '4': 3 }, {});
  const rIT = plIT.rows.find(r => r.productId === 'P4');
  assert.strictEqual(rIT.zeroRestock, true);
  assert.strictEqual(rIT.restock, 0);

  // Verify splitForecastAcrossLanes (KI-2 fix)
  const mockReportMultiLane = [
    ['Machine','No.','Product ID','Product Name','Bal Qty','Lane Size','Restock'],
    ['MachY', '1', 'P362', 'Water', '5', '10', '3'],
    ['MachY', '2', 'P362', 'Water', '5', '10', '3'],
    ['MachY', '3', 'P362', 'Water', '5', '10', '3'],
    ['MachY', '4', 'P362', 'Water', '5', '10', '3'],
    ['MachY', '5', 'P999', 'Soda',  '5', '10', '3'],  // single-lane PID
  ];
  const split = splitForecastAcrossLanes(mockReportMultiLane, 'MachY', { P362: 20, P999: 8, P404: 5 });
  assert.strictEqual(split.P362, 5);   // 20 / 4 lanes
  assert.strictEqual(split.P999, 8);   // 1 lane -> unchanged
  assert.strictEqual(split.P404, 5);   // PID not on this machine's report -> unchanged
  assert.deepStrictEqual(splitForecastAcrossLanes(mockReportMultiLane, 'MachY', {}), {});

  // Verify listMachineLanes + suggestReplacements (Q3)
  const mockReportQ3 = [
    ['Machine','No.','Product ID','Product Name','Bal Qty','Lane Size','Restock'],
    ['MachZ', '1', 'P10', 'SlowCola',  '2', '6', '3'],  // slow: sales 2 vs tray avg 10
    ['MachZ', '2', 'P11', 'FastCola',  '2', '6', '3'],  // healthy: sales 18
    ['MachZ', '3', 'P11', 'FastCola',  '2', '6', '3'],  // same pid 2nd lane (dedupe test)
    ['MachZ', '4', 'P20', 'WarmChips', '2', '8', '3'],  // different tray
    ['OtherM','1', 'P10', 'SlowCola',  '2', '6', '3'],  // other machine, must be ignored
  ];
  const q3Lanes = listMachineLanes(mockReportQ3, 'MachZ');
  assert.strictEqual(q3Lanes.length, 4);
  assert.deepStrictEqual(q3Lanes[0], { laneNo: '1', pid: 'P10', product: 'SlowCola', laneSize: 6 });

  const q3Catalog = {
    P10: { name: 'SlowCola',   tray: 'COLD 1', size: 6 },
    P11: { name: 'FastCola',   tray: 'COLD 1', size: 6 },
    P12: { name: 'NewJuice',   tray: 'COLD 1', size: 6 },  // not stocked, top global seller
    P13: { name: 'DeadJuice',  tray: 'COLD 1', size: 6 },  // zero global sales → excluded
    P14: { name: 'WrongSize',  tray: 'COLD 1', size: 8 },  // size mismatch → excluded
    P20: { name: 'WarmChips',  tray: 'WARM 2', size: 8 },
  };
  // tray COLD 1 stocked pids: P10 (2) + P11 (18) → avg 10; P10 slow at 50% (2 < 5), P11 not (18 >= 5)
  const q3MachineSales = { P10: 2, P11: 18, P20: 7 };
  const q3GlobalSales  = { P10: 40, P11: 900, P12: 1500, P20: 300 };
  const pickRowsQ3 = [
    { laneNo: '1', productId: 'P10', lane: 6 },
    { laneNo: '2', productId: 'P11', lane: 6 },
    { laneNo: '9', productId: 'P99', lane: 6 },  // not in catalog → skipped
  ];
  const sug = suggestReplacements(pickRowsQ3, q3Lanes, q3Catalog, q3MachineSales, q3GlobalSales, 50);
  assert.deepStrictEqual(Object.keys(sug), ['1']);              // only the slow lane
  const cands = sug['1'].candidates;
  assert.strictEqual(cands.length, 2);                          // P12 + P11 (P13 zero sales, P14 wrong size)
  assert.strictEqual(cands[0].pid, 'P12');                      // global 1500 first
  assert.strictEqual(cands[0].inLane, null);                    // not stocked here
  assert.strictEqual(cands[1].pid, 'P11');
  assert.strictEqual(cands[1].inLane, '2');                     // stocked → first lane it occupies
  // threshold sensitivity: at 5% avg=10 → bar 0.5, P10 sales 2 no longer slow
  assert.deepStrictEqual(suggestReplacements(pickRowsQ3, q3Lanes, q3Catalog, q3MachineSales, q3GlobalSales, 5), {});
  // empty catalog → no suggestions, no crash
  assert.deepStrictEqual(suggestReplacements(pickRowsQ3, q3Lanes, {}, q3MachineSales, q3GlobalSales, 50), {});

  console.log("picking.js self-check OK");
}
