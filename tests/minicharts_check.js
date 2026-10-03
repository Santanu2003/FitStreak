// Renders every chart shape used by FitStreak with the offline renderer and checks the
// output is well-formed (no NaN/undefined) and that labels are HTML-escaped.
// Run automatically by tests/test_app.py when Node.js is available.
const MC = require(require('path').join(__dirname,'..','frontend','js','minicharts.js'));
const dual = (a,b,la,lb,ta,tb)=>({type:'bar',data:{labels:['<1','1-2','2-3','3+'],datasets:[{label:la,data:a,backgroundColor:'#C9DE3B',yAxisID:'y'},{label:lb,data:b,backgroundColor:'#14201A',yAxisID:'y1'}]},options:{scales:{y:{title:{display:true,text:ta}},y1:{title:{display:true,text:tb}}}}});
const cases = {
  history_line: {type:'line',data:{labels:['2026-09-20','2026-09-21','2026-09-22','2026-09-23','2026-09-24'],datasets:[{label:'Calories burned',data:[280,300,310,290,330],borderColor:'#3F5A34',backgroundColor:'rgba(201,222,59,0.25)',fill:true}]},options:{plugins:{legend:{display:false}},scales:{y:{beginAtZero:true}}}},
  history_single_point: {type:'line',data:{labels:['2026-09-20'],datasets:[{label:'c',data:[280],borderColor:'#3F5A34',fill:true}]}},
  activity_hbar: {type:'bar',data:{labels:['HIIT','Running','Cycling','Yoga'],datasets:[{label:'kcal / min',data:[0.37,0.30,0.26,0.09],backgroundColor:'#3F5A34'}]},options:{indexAxis:'y',plugins:{legend:{display:false}},scales:{x:{title:{display:true,text:'kcal per minute'}}}}},
  benchmark_dual: dual([10995,10788,11260,10627],[5.1,4.9,5.0,5.0],'Avg daily steps','Avg exercise hrs/week','Steps','Hours/week'),
  insights_dual: dual([3.27,3.25,3.19,3.06],[8.6,8.29,8.07,7.11],'Avg GPA','Avg sleep (hrs)','GPA','Sleep hrs'),
  bmi_dual_lines: {type:'line',data:{labels:['2026-09-20','2026-09-24','2026-09-28'],datasets:[{label:'BMI',data:[22.8,22.0,21.6],borderColor:'#3F5A34',backgroundColor:'rgba(201,222,59,0.25)',fill:true,yAxisID:'y'},{label:'Weight (kg)',data:[62,60,58.8],borderColor:'#14201A',borderDash:[5,4],yAxisID:'y1'}]},options:{scales:{y:{title:{display:true,text:'BMI'}},y1:{title:{display:true,text:'kg'}}}}},
  macro_doughnut: {type:'doughnut',data:{labels:['Protein (g)','Carbs (g)','Fat (g)'],datasets:[{data:[40,120,30],backgroundColor:['#3F5A34','#C9DE3B','#E4573F']}]}},
  doughnut_single: {type:'doughnut',data:{labels:['A','B'],datasets:[{data:[50,0],backgroundColor:['#3F5A34','#C9DE3B']}]}},
  empty: {type:'bar',data:{labels:[],datasets:[]}},
  xss_label: {type:'bar',data:{labels:['<img src=x onerror=alert(1)>'],datasets:[{label:'"><script>',data:[3],backgroundColor:'#3F5A34'}]}},
  many_dates: {type:'line',data:{labels:Array.from({length:40},(_,i)=>'2026-08-'+String(i+1).padStart(2,'0')),datasets:[{label:'x',data:Array.from({length:40},(_,i)=>200+i*3%50),borderColor:'#3F5A34',fill:true}]}},
};
let bad = 0;
for (const [name,cfg] of Object.entries(cases)) {
  const svg = MC.toSvg(cfg,{width:600,height:240});
  const problems = [];
  if (/NaN|undefined|Infinity/.test(svg)) problems.push('NaN/undefined/Infinity in output');
  if (!svg.startsWith('<svg')) problems.push('not svg');
  if (/<img|<script/.test(svg)) problems.push('UNESCAPED HTML');
  console.log(name.padEnd(22), svg.length+'b', 'rects',(svg.match(/<rect/g)||[]).length,'circles',(svg.match(/<circle/g)||[]).length,'paths',(svg.match(/<path/g)||[]).length, problems.length?'PROBLEM: '+problems.join(','):'ok');
  if (problems.length) bad++;
}
console.log(bad ? 'FAILED '+bad : 'ALL OK');
process.exit(bad?1:0);
