import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  applyKey,
  discountedPrice,
  formatDateTime,
  formatDecimal,
  formatLei,
  formatPercent,
  formatQuantity,
  formatShare,
  lineTotalBani,
  localIsoDate,
  parseDecimal,
  parseEntry,
} from './money.js'

test('applyKey: tastatura numerică de pe ecran', () => {
  const type = (keys, decimals) => keys.reduce((text, key) => applyKey(text, key, decimals), '')
  assert.equal(type(['1', ',', '2', '5', '0'], 3), '1,250')        // kg
  assert.equal(type(['1', ',', '2', '5', '0', '9'], 3), '1,250')   // a patra zecimală ignorată
  assert.equal(type(['1', '2', ',', '5', '0', '0'], 2), '12,50')   // preț: doar două zecimale
  assert.equal(type([',', '7', '5'], 3), '0,75')
  assert.equal(type(['0', '0', '5'], 2), '5')
  assert.equal(type(['5', ',', ','], 2), '5,')
  assert.equal(type(['3', ','], 0), '3')                           // bucăți: fără virgulă
  assert.equal(type(['9', '9', '9', '9', '9', '9', '9', '9'], 2), '9999999')
  assert.equal(type(['1', '2', 'back'], 2), '1')
  assert.equal(type(['1', '2', 'clear', '4'], 2), '4')
  assert.equal(applyKey('1.2', '5', 3), '1,25')                    // punct tastat pe tastatura fizică
  assert.equal(parseDecimal(type(['1', ',', '2', '5'], 3), 3), 1250)
})

test('formatShare, localIsoDate, formatDateTime', () => {
  assert.equal(formatShare(1350, 3684), '36,6%')
  assert.equal(formatShare(1, 3), '33,3%')
  assert.equal(formatShare(5, 5), '100,0%')
  assert.equal(formatShare(5, 0), '—')
  assert.equal(localIsoDate(new Date(2026, 0, 5, 23, 59)), '2026-01-05')
  assert.equal(formatDateTime('2026-10-19 18:30:01'), '19.10.2026 18:30')
  assert.equal(formatDateTime(null), '')
})

test('formatLei', () => {
  assert.equal(formatLei(0), '0,00')
  assert.equal(formatLei(5), '0,05')
  assert.equal(formatLei(1250), '12,50')
  assert.equal(formatLei(100000), '1.000,00')
  assert.equal(formatLei(123456789), '1.234.567,89')
})

test('formatDecimal and formatQuantity', () => {
  assert.equal(formatDecimal(1250, 3), '1,250')
  assert.equal(formatDecimal(50, 2), '0,50')
  assert.equal(formatDecimal(7, 0), '7')
  assert.equal(formatQuantity(3000, 'unit'), '3 buc')
  assert.equal(formatQuantity(750, 'weight'), '0,750 kg')
})

test('parseDecimal accepts comma or dot and stays integer', () => {
  assert.equal(parseDecimal('12,5', 2), 1250)
  assert.equal(parseDecimal('12.50', 2), 1250)
  assert.equal(parseDecimal(' 7 ', 2), 700)
  assert.equal(parseDecimal('12,', 2), 1200)
  assert.equal(parseDecimal(',75', 3), 750)
  assert.equal(parseDecimal('19,99', 2), 1999)          // float: 19.99 * 100 = 1998.9999999999998
  assert.equal(parseDecimal('0,1', 2) + parseDecimal('0,2', 2), 30)
  assert.equal(parseDecimal('1,005', 3), 1005)
})

test('parseDecimal rejects anything else', () => {
  for (const text of ['', ' ', ',', '1,234', '-1', '1e3', 'abc', '1,2,3', '12 50', '1.000,50', '9999999999999']) {
    assert.equal(parseDecimal(text, 2), null, text)
  }
})

test('discountedPrice rounds half up like the backend; formatPercent', () => {
  assert.deepEqual([discountedPrice(899, 1000), discountedPrice(699, 1416), discountedPrice(889, 5000),
    discountedPrice(450, 0), discountedPrice(450, 1250)], [809, 600, 445, 450, 394])
  assert.deepEqual([formatPercent(1000), formatPercent(1250), formatPercent(1416), formatPercent(5), formatPercent(2000)],
    ['10', '12,5', '14,16', '0,05', '20'])
})

test('lineTotalBani rounds half up like the backend', () => {
  assert.equal(lineTotalBani(2500, 101), 253)
  assert.equal(lineTotalBani(1250, 899), 1124)
  assert.equal(lineTotalBani(10_000_000, 99_999_999), 999_999_990_000)
})

test('parseEntry', () => {
  assert.deepEqual(parseEntry(' 200 '), { quantityMilli: null, code: '200' })
  assert.deepEqual(parseEntry('3*200'), { quantityMilli: 3000, code: '200' })
  assert.deepEqual(parseEntry('1,250 * 101'), { quantityMilli: 1250, code: '101' })
  assert.deepEqual(parseEntry('2*'), { quantityMilli: 2000, code: '' })
  assert.equal(parseEntry('0*200'), null)
  assert.equal(parseEntry('x*200'), null)
})
