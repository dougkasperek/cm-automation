#!/usr/bin/env node
// How much header a reader scrolls past before the first data row.
//
// Written 2026-08-29. Every earlier session measured this by hand and quoted a
// number the next session could not reproduce -- the 2026-08-29 handoff has a
// table of four such figures and a note that one of them was wrong because it
// counted the lane strip twice after the strip moved inside the banner. A
// script cannot make that mistake twice in the same way, and it states its own
// definitions, which a sentence in a handoff does not.
//
//   node _scratch/measure-page.mjs [PATH.html]
//
// RENDER FIRST. Like test-page.mjs, this opens a file and renders nothing.
//
// Definitions, so a later session can tell whether it is comparing like
// with like:
//   firstRow    viewport-relative top of the first matrix data row, at
//               1280x900 scrolled to the top. "Header before the data."
//   pageHeight  scrollHeight of the whole Evidence tab.
//   chromeWords whitespace-separated tokens in everything that precedes
//               table.matrix in document order, tab controls included.
import { chromium } from 'playwright';
import { resolve } from 'node:path';

const file = resolve(process.argv[2] || 'fleet.html');
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
await page.goto('file://' + file);
await page.waitForSelector('table.matrix tbody tr.row');

const m = await page.evaluate(() => {
  const table = document.querySelector('table.matrix');
  const row = document.querySelector('table.matrix tbody tr.row');
  // Everything before the matrix in document order. A TreeWalker rather than
  // a parent chain: the banner, the cards and the tools row are siblings at
  // different depths, and "text above the table" is the reader's question.
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let words = 0, n;
  while ((n = w.nextNode())) {
    if (table.compareDocumentPosition(n) & Node.DOCUMENT_POSITION_PRECEDING) {
      if (n.parentElement.closest('script, style')) continue;
      const t = n.textContent.trim();
      if (t) words += t.split(/\s+/).length;
    }
  }
  return {
    firstRow: Math.round(row.getBoundingClientRect().top),
    pageHeight: document.documentElement.scrollHeight,
    chromeWords: words,
  };
});

console.log('file        ' + file);
console.log('firstRow    ' + m.firstRow + 'px');
console.log('pageHeight  ' + m.pageHeight + 'px');
console.log('chromeWords ' + m.chromeWords);
await browser.close();
