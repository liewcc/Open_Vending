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
 * Determines which machines qualify for picking today.
 * @param {any[][]} reportRows
 * @param {object} routePlan
 * @param {Date} date
 * @param {object} pendingByMachine - {machineName: {laneNo: qty, ...}, ...}
 * @returns {object[]}
 */
function machinesToPickToday(reportRows, routePlan, date, pendingByMachine) {
  if (!pendingByMachine) pendingByMachine = {};
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
      if (!machinesInPlan[machineName]) {
        continue;
      }
      const machinePlan = machinesInPlan[machineName];
      const rows = groups[machineName];

      let laneSum = 0;
      let restockSum = 0;
      for (const r of rows) {
        laneSum += num(r[5]);    // Lane Size is col 5
        restockSum += num(r[6]); // Restock is col 6
      }

      // In-transit deduction: sum all pending picked_qty for this machine
      const lanePending = pendingByMachine[machineName] || {};
      const inTransitSum = Object.values(lanePending).reduce((a, v) => a + v, 0);
      const adjustedRestockSum = Math.max(0, restockSum - inTransitSum);

      const pctRaw = laneSum > 0 ? adjustedRestockSum / laneSum : 0;
      const pct = Math.round(pctRaw * 100) / 100;

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
          restockSum,
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
 * Builds the picking list for a single machine.
 * @param {any[][]} reportRows
 * @param {string} machine
 * @param {object} pendingByLane - {laneNo: qty, ...}
 * @param {object} oosByLane - {laneNo: count, ...}
 * @returns {object}
 */
function buildPickingList(reportRows, machine, pendingByLane, oosByLane) {
  if (!pendingByLane) pendingByLane = {};
  if (!oosByLane) oosByLane = {};

  // Take only data rows whose column 0 === machine
  const machineRows = [];
  for (let i = 1; i < reportRows.length; i++) {
    const row = reportRows[i];
    if (row && row[0] === machine) {
      machineRows.push(row);
    }
  }

  const visibleRows = [];
  let hiddenCount = 0;

  for (const row of machineRows) {
    const restock = num(row[6]); // Restock is col 6
    const laneNo = String(row[1]); // No. column
    const laneInTransit = pendingByLane[laneNo] || 0;
    const actualRestock = Math.max(0, restock - laneInTransit);

    // Step B: hide if actualRestock === 0
    if (actualRestock === 0) {
      hiddenCount++;
      continue;
    }

    const bal = num(row[4]); // Bal Qty is col 4
    // Step C: drop rows where num(balQty) > 10
    if (bal > 10) {
      hiddenCount++;
      continue;
    }

    // Step A: out of stock
    const outOfStock = (bal === 0);

    // Step D: fast-mover +1
    const oos7 = oosByLane[laneNo] || 0;
    const finalRestock = oos7 >= 2 ? actualRestock + 1 : actualRestock;

    visibleRows.push({
      no: row[1],
      productId: row[2],
      product: row[3] !== undefined && row[3] !== null ? String(row[3]) : '',
      bal,
      lane: num(row[5]),
      restock: finalRestock,
      outOfStock,
      laneNo
    });
  }

  return {
    machine,
    rows: visibleRows,
    hiddenCount
  };
}

module.exports = {
  num,
  weekdayName,
  machinesToPickToday,
  buildPickingList
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

  // Verify buildPickingList
  const mockReportList = [
    ['Machine','No.','Product ID','Product Name','Bal Qty','Lane Size','Restock'],
    ['MachX', '1', 'P1', 'A', '5', '10', '0'],   // restock === 0 -> drop (Step B)
    ['MachX', '2', 'P2', 'B', '11', '10', '2'],  // balQty === 11 (> 10) -> drop (Step C)
    ['MachX', '3', 'P3', 'C', '0', '10', '4'],   // balQty === 0 (<=10, restock>0) -> survive, outOfStock = true
    ['MachX', '4', 'P4', 'D', '5', '10', '3'],   // balQty === 5 (<=10, restock>0) -> survive, outOfStock = false
  ];

  const pickList = buildPickingList(mockReportList, 'MachX', {}, {});
  assert.strictEqual(pickList.machine, 'MachX');
  assert.strictEqual(pickList.hiddenCount, 2);
  assert.strictEqual(pickList.rows.length, 2);

  assert.strictEqual(pickList.rows[0].productId, 'P3');
  assert.strictEqual(pickList.rows[0].outOfStock, true);
  assert.strictEqual(pickList.rows[0].bal, 0);
  assert.strictEqual(pickList.rows[0].restock, 4);

  assert.strictEqual(pickList.rows[1].productId, 'P4');
  assert.strictEqual(pickList.rows[1].outOfStock, false);
  assert.strictEqual(pickList.rows[1].bal, 5);
  assert.strictEqual(pickList.rows[1].restock, 3);

  console.log("picking.js self-check OK");
}
