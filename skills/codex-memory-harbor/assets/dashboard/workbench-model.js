/* Pure selection/ordering rules shared by the UI and regression tests. */
(function(root){
  const recommendedItems=sessions=>sessions.filter(item=>item.eligible&&!item.linked&&!item.catalog_only);
  const sortItems=(items,order)=>[...items].sort((a,b)=>order==='recent'?(b.age_days??-1)-(a.age_days??-1)||(b.logical||b.bytes||0)-(a.logical||a.bytes||0):(b.logical||b.bytes||0)-(a.logical||a.bytes||0)||(b.age_days??-1)-(a.age_days??-1));
  function selectedObjects(sessions,plans,selected,files){return[...sessions.filter(row=>selected.has(row.path)&&row.eligible&&!row.linked).map(row=>({kind:'history',path:row.path})),...plans.flatMap(plan=>plan.files.files.filter(row=>files.has(row.source)).map(row=>({kind:'file',path:row.source,plan_id:plan.plan_id})))];}
  function pruneSelection(sessions,selected){const valid=new Set(sessions.filter(row=>row.eligible||row.linked).map(row=>row.path));for(const path of selected)if(!valid.has(path))selected.delete(path);}
  function taskPresentation(row,label,translate){const info=label||row;return{title:info.title||row.title||translate(row.kind==='main'?'unnamedTask':'unnamedChild'),summary:row.match_excerpt||info.summary||row.summary||translate(info.task_label_ready||row.task_label_ready?'taskInfoMissing':'taskInfoPending')};}
  const api={recommendedItems,sortItems,selectedObjects,pruneSelection,taskPresentation};if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.HarborWorkbench=api;
})(typeof window!=='undefined'?window:this);
