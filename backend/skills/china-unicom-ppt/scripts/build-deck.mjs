#!/usr/bin/env node
// One positioned source generates native editable PPTX and the companion PPTD.
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const [inputPath, outputDir] = process.argv.slice(2);
if (!inputPath || !outputDir) throw new Error('Usage: build-deck.mjs content.json /absolute/project-dir');
const runtimeModules = process.env.RUNTIME_NODE_MODULES;
if (!runtimeModules) throw new Error('Set RUNTIME_NODE_MODULES from load_workspace_dependencies.');
const require = createRequire(path.join(runtimeModules, '_unicom.cjs'));
const { Presentation, PresentationFile } = await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
const spec = JSON.parse(await fs.readFile(inputPath, 'utf8'));
const root = path.resolve(outputDir);
const privateDir = path.join(root, '.build');
await Promise.all(['media','pages','previews','.build'].map(d => fs.mkdir(path.join(root,d),{recursive:true})));
const skill = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
await fs.copyFile(path.join(skill,'assets/logo.png'),path.join(root,'media/logo.png'));
const FONT = spec.font || 'Microsoft YaHei';
const RED = '#E60027';
const ppt = Presentation.create({slideSize:{width:1280,height:720}});
const pages = [];
let serial = 0;
function checkBounds(e) {
  if (!Array.isArray(e.bounds) || e.bounds.length !== 4 || e.bounds.some(x=>!Number.isFinite(x))) throw new Error('Invalid bounds');
  const [x,y,w,h]=e.bounds;
  if(x<0||y<0||w<=0||h<=0||x+w>1280.1||y+h>720.1) throw new Error(`Element outside slide: ${JSON.stringify(e)}`);
}
function baseElements(s,i) {
  if(s.kind==='cover') return [
    {type:'image',src:'media/logo.png',bounds:[850,55,360,106]},
    {type:'rect',fill:RED,bounds:[155,294,5,320]},
    {type:'text',text:s.title,bounds:[214,306,945,110],size:54,bold:true},
    {type:'text',text:s.subtitle||'',bounds:[220,470,900,40],size:26},
    {type:'text',text:s.date||'',bounds:[220,550,900,40],size:26,bold:true}
  ];
  if(s.kind==='end') return [
    {type:'image',src:'media/logo.png',bounds:[1028,28,220,65]},
    {type:'text',text:s.title,bounds:[170,300,940,100],size:58,bold:true,align:'center'},
    {type:'text',text:s.subtitle||'',bounds:[270,420,740,40],size:25,color:'#666666',align:'center'}
  ];
  return [
    {type:'text',text:s.title,bounds:[32,32,980,54],size:32,bold:true},
    {type:'image',src:'media/logo.png',bounds:[1088,10,165,49]},
    {type:'rect',fill:RED,bounds:[0,86,1280,3]},
    {type:'text',text:String(i+1),bounds:[1215,680,40,24],size:16,align:'right'},
    ...(s.sourceLabel?[{type:'text',text:s.sourceLabel,bounds:[44,668,1135,35],size:13,color:'#707070'}]:[])
  ];
}
for (const [i,s] of spec.slides.entries()) {
  const slide = ppt.slides.add();
  slide.background.fill = '#FFFFFF';
  const elements = [...baseElements(s,i),...(s.elements||[])];
  const page = {pageType:s.kind||'content',background:{type:'solid',color:'#FFFFFF'},elements:[]};
  if(s.sources?.length) slide.speakerNotes.text = s.sources.map(u=>`来源：${u}`).join('\n');
  for (const e of elements) {
    checkBounds(e);
    const [left,top,width,height]=e.bounds;
    const position={left,top,width,height};
    const id=`e${++serial}`;
    const base={elementId:id,bounds:e.bounds.map(v=>v*.75)};
    if(e.type==='text') {
      const sh=slide.shapes.add({geometry:'textbox',name:id,position,fill:'none',line:{fill:'none',width:0}});
      sh.text=e.text;
      sh.text.style={fontSize:e.size||24,typeface:FONT,color:e.color||'#161616',bold:!!e.bold,alignment:e.align||'left',verticalAlignment:e.valign||'top',wrap:'square',autoFit:'none',insets:0,lineSpacing:1.16};
      page.elements.push({...base,elementType:'text',content:{text:e.text,fontSize:(e.size||24)*.75,fontFamily:FONT,color:e.color||'#161616',bold:!!e.bold,lineHeight:1.16,align:[e.align||'left',e.valign||'top']}});
    } else if(e.type==='rect') {
      slide.shapes.add({geometry:'rect',name:id,position,fill:e.fill,line:{fill:'none',width:0}});
      page.elements.push({...base,elementType:'shape',shapeName:'rect',fill:{type:'solid',color:e.fill}});
    } else if(e.type==='image') {
      const mediaPath=path.resolve(root,e.src);
      if(!mediaPath.startsWith(root+path.sep)) throw new Error('Media must be inside project');
      const bytes=await fs.readFile(mediaPath);
      slide.images.add({blob:bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),contentType:e.src.endsWith('.png')?'image/png':'image/jpeg',alt:e.alt||'',position,fit:e.fit||'contain'});
      page.elements.push({...base,elementType:'image',src:e.src,fit:{mode:e.fit||'contain'}});
    } else if(e.type==='chart') {
      if(!e.values?.length || e.values.length!==e.categories?.length || e.values.some(v=>!Number.isFinite(v)||v<0)) throw new Error('Column chart requires matching categories and nonnegative numeric values');
      const peak=Math.max(...e.values,1);
      const magnitude=10**Math.floor(Math.log10(peak));
      const axisMax=e.axisMax ?? Math.ceil(peak*1.12/magnitude)*magnitude;
      if(axisMax<peak) throw new Error('axisMax must include all values');
      const chart=slide.charts.add('bar',{position,categories:e.categories,series:[{name:e.seriesName,values:e.values,fill:RED}],hasLegend:false,barOptions:{direction:'column',gapWidth:100},chartFill:'#FFFFFF',plotAreaFill:'#FFFFFF',xAxis:{textStyle:{fontSize:17,typeface:FONT},visible:true},yAxis:{min:0,max:axisMax,majorUnit:e.majorUnit??axisMax/4,numberFormatCode:'0',textStyle:{fontSize:14,typeface:FONT},majorGridlines:{fill:'#E2E2E2',width:.5}},dataLabels:{showValue:true,position:'outEnd',textStyle:{fontSize:15,typeface:FONT},numberFormatCode:'0.0'}});
      page.elements.push({...base,elementType:'chart',data:{cols:['年份','收入'],rows:e.categories.map((c,j)=>[c,e.values[j]])},series:[{type:'bar',name:e.seriesName,encode:{x:'年份',y:'收入'},fill:RED}],fontFamily:FONT,legend:false,xAxis:{type:'category',label:{fontSize:13}},yAxis:{type:'value',min:0,max:axisMax,numberFormat:'0'},dataLabels:{show:true,content:'value',fontSize:11,position:'outside'}});
    } else if(e.type==='table') {
      const table=slide.tables.add({rows:e.rows.length,columns:e.rows[0].length,left,top,width,height,columnWidths:e.widths,values:e.rows});
      table.borders.assign({fill:'#D8D8D8',width:.7,style:'solid'});
      for(let r=0;r<e.rows.length;r++) for(let c=0;c<e.rows[0].length;c++) {
        const cell=table.getCell(r,c);
        cell.fill=r===0?RED:r%2?'#FFFFFF':'#F4F4F4';
        cell.text.style={fontSize:e.size||22,typeface:FONT,bold:r===0,color:r===0?'#FFFFFF':'#242424',alignment:'left',verticalAlignment:'middle',insets:{left:16,right:14,top:10,bottom:10}};
      }
      const total=e.widths.reduce((a,b)=>a+b,0);
      page.elements.push({...base,elementType:'table',columnWidths:e.widths.map(w=>w/total),rowHeights:e.rows.map(()=>1/e.rows.length),rows:e.rows.map((row,r)=>row.map(text=>({text,fontFamily:FONT,fontSize:(e.size||22)*.75,bold:r===0,color:r===0?'#FFFFFF':'#242424',fill:{type:'solid',color:r===0?RED:r%2?'#FFFFFF':'#F4F4F4'},border:{color:'#D8D8D8',width:.5},align:['left','middle']})))});
    } else throw new Error(`Unsupported element type ${e.type}`);
  }
  const name=`pages/${String(i+1).padStart(2,'0')}.page`;
  pages.push(name);
  await fs.writeFile(path.join(root,name),JSON.stringify(page,null,2));
  const png=await ppt.export({slide,format:'png',scale:1.25});
  await fs.writeFile(path.join(root,'previews',`${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await png.arrayBuffer()));
}
await fs.writeFile(path.join(root,'deck.pptd'),JSON.stringify({version:'v2',title:spec.title,size:[960,540],theme:{colors:{primary:RED},textStyles:{body:{fontFamily:FONT,fontSize:18}}},pages},null,2));
await (await PresentationFile.exportPptx(ppt)).save(path.join(privateDir,'draft.pptx'));
console.log(JSON.stringify({slides:spec.slides.length,draft:path.join(privateDir,'draft.pptx'),project:root}));
