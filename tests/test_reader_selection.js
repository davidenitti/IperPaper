// Run with: node tests/test_reader_selection.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

// A linear DOM range fixture gives text nodes stable document coordinates.
class TextRange {
  static START_TO_START = 0;
  static END_TO_END = 2;
  constructor(startNode, startOffset, endNode, endOffset) {
    Object.assign(this, {startContainer:startNode, startOffset, endContainer:endNode, endOffset});
  }
  get start() { return this.startContainer.position + this.startOffset; }
  get end() { return this.endContainer.position + this.endOffset; }
  get collapsed() { return this.start >= this.end; }
  selectNodeContents(node) { this.setStart(node, 0); this.setEnd(node, node.nodeValue.length); }
  setStart(node, offset) { this.startContainer=node; this.startOffset=offset; }
  setEnd(node, offset) { this.endContainer=node; this.endOffset=offset; }
  intersectsNode(node) { return this.start < node.position+node.nodeValue.length && this.end > node.position; }
  compareBoundaryPoints(kind, other) { return kind===0 ? this.start-other.start : this.end-other.end; }
}
function sourceFunction(template, name) {
  return template.split('\n').find(line => line.startsWith(`function ${name}(`));
}
for (const mode of ['pdf', 'native']) {
  const template = fs.readFileSync(`iperpaper_templates/${mode}_reader.html`, 'utf8');
  const context = vm.createContext({Range:TextRange, Node:{TEXT_NODE:3}, document:{createRange:()=>new TextRange()}});
  vm.runInContext(sourceFunction(template, 'selectedModelBounds'), context);
  const first={nodeType:3, position:0, nodeValue:'First sentence. Second sentence.'};
  const next={nodeType:3, position:100, nodeValue:'Another paragraph.'};
  const model={segments:[{node:first,start:0,end:first.nodeValue.length},{node:next,start:40,end:58}]};
  const select = range => ({rangeCount:1,getRangeAt:()=>range});
  const bounds = range => JSON.parse(JSON.stringify(context.selectedModelBounds(model, select(range))));
  assert.deepEqual(bounds(new TextRange(first,6,first,14)), {start:6,end:14}, `${mode}: partial sentence`);
  assert.deepEqual(bounds(new TextRange(first,6,first,22)), {start:6,end:22}, `${mode}: multiple sentences`);
  assert.deepEqual(bounds(new TextRange(first,6,next,7)), {start:6,end:47}, `${mode}: multiple blocks`);
  assert.deepEqual(JSON.parse(JSON.stringify(context.selectedModelBounds({segments:[model.segments[1]]}, select(new TextRange(first,6,next,7))))), {start:40,end:47}, `${mode}: clip to next page/block`);
  assert.equal(bounds(new TextRange(first,6,first,6)), null, `${mode}: collapsed selection`);

  // Selected text must win before caret lookup, sentence detection, or removal.
  const handlerName = mode==='pdf' ? 'pdfHighlightContextMenu' : 'nativeHighlightContextMenu';
  const contentSelector = mode==='pdf' ? '#viewer' : '.ip-paper';
  let selectedCalls=0;
  context[mode==='pdf' ? 'highlightPdfSelection' : 'highlightNativeSelection']=()=>{selectedCalls++; return true;};
  context.caretAtPoint=()=>{throw Error('Selection must bypass caret lookup');};
  vm.runInContext(sourceFunction(template,handlerName), context);
  context[handlerName]({target:{closest:selector=>selector===contentSelector ? {} : null}});
  assert.equal(selectedCalls,1, `${mode}: prioritize selected range`);
  context[handlerName]({target:{closest:()=>({})}});
  assert.equal(selectedCalls,1, `${mode}: leave controls alone`);
}
const pdf = fs.readFileSync('iperpaper_templates/pdf_reader.html','utf8');
const pdfContext=vm.createContext({storedHighlightRange:()=>{throw Error('Do not expand a saved selection');}});
vm.runInContext(sourceFunction(pdf,'repairPdfHighlight'),pdfContext);
assert.equal(pdfContext.repairPdfHighlight({kind:'selection'}, {}, {}),false);
const native = fs.readFileSync('iperpaper_templates/native_reader.html','utf8');
const saved={kind:'selection',block:0,start:6,exact:'sentence',prefix:'First '};
const nativeContext=vm.createContext({userHighlights:[saved]});
for(const name of ['repairNativeHighlight','storedHighlightStart','nativeHighlightAt'])vm.runInContext(sourceFunction(native,name),nativeContext);
assert.equal(nativeContext.repairNativeHighlight(saved),saved);
assert.equal(nativeContext.nativeHighlightAt({text:'First sentence. Second sentence.'},0,8),saved);
console.log('Selection highlighting checks passed for both readers.');

// Display equations delimit prose even when introduced by a colon; inline math stays.
for (const intl of [Intl, {}]) {
  const context=vm.createContext({Intl:intl, document:{documentElement:{lang:'en'}}});
  for (const name of ['sentenceBounds','nativeSentenceBounds','repairNativeHighlight','storedHighlightStart'])
    vm.runInContext(sourceFunction(native,name),context);
  const text='At position t, assign probabilities: \nFORMULA\nwhere p is positive. Next sentence.';
  const formulaStart=text.indexOf('FORMULA'), formulaEnd=formulaStart+7;
  const model={text,sentenceText:text,segments:[
    {type:'element',start:12,end:13,element:{matches:()=>false}},
    {type:'element',start:formulaStart,end:formulaEnd,element:{matches:selector=>selector==='.math.display'}}
  ]};
  const selected=offset=>{const b=context.nativeSentenceBounds(model,offset);return text.slice(b.start,b.end);};
  assert.equal(selected(3),'At position t, assign probabilities:');
  assert.equal(selected(12),'At position t, assign probabilities:');
  assert.equal(selected(formulaEnd+4),'where p is positive.');
  assert.equal(selected(text.indexOf('Next')),'Next sentence.');
  context.HIGHLIGHT_BLOCK_SELECTOR='p';
  context.document.querySelectorAll=()=>[{}];
  context.nativeTextModel=()=>model;
  const repaired=context.repairNativeHighlight({kind:'sentence',block:0,start:0,exact:text.slice(0,formulaEnd)});
  assert.equal(repaired.exact,'At position t, assign probabilities:');
}
console.log('Native prose excludes display equations, including saved highlights.');
