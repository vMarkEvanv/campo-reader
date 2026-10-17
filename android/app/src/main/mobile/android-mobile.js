/* Packaged phone UI only. Official Campo pages never get this bridge. */
'use strict';
(()=>{
 document.documentElement.classList.add('android-app');
 ['desktop-check-update','desktop-data-folder'].forEach(id=>{const el=document.getElementById(id);if(el)el.remove();});
 const about=document.createElement('button');about.className='settings-button';about.textContent='关于 Campo Reader';about.id='android-about';about.onclick=()=>CampoMobile.about();document.querySelector('.sidebar-bottom').append(about);
 document.addEventListener('click',e=>{const link=e.target.closest('a.download-button');if(!link||!link.pathname.endsWith('/api/campo/document'))return;e.preventDefault();e.stopImmediatePropagation();CampoMobile.exportPdf(link.href,link.download||'Campo document.pdf');},true);
 const header=document.querySelector('#settings-form .setting-row small');if(header)header.textContent='在应用前台按设定间隔更新；切到后台或关闭后暂停。';
 const description=document.querySelector('.subtitle');if(description)description.textContent='课表与成绩 · 自动同步';
 document.querySelector('.page-nav').addEventListener('click',()=>{if(description)description.textContent='课表与成绩 · 自动同步';});
 const week=document.getElementById('week');
 const date=new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Berlin'}).format(new Date());
 // Compact day controls use the existing week data and navigation.
 const days=document.createElement('div');days.className='mobile-days';days.setAttribute('aria-label','选择日期');
 week.before(days);let activeDay=date;
 function dayMode(){
  const columns=Array.from(week.children);if(!columns.length)return;days.replaceChildren();
  columns.forEach((column,i)=>{const heading=column.querySelector('h3');const label=heading?Array.from(heading.children).map(e=>e.textContent).join(' '):String(i+1);column.dataset.dayIndex=i;
   const b=document.createElement('button');b.textContent=label;b.type='button';b.onclick=()=>{activeDay=String(i);show();};days.append(b);
  });
  if(!/^\d$/.test(activeDay)){const today=columns.findIndex(c=>c.classList.contains('today')||(c.querySelector('h3')||{}).textContent&&c.querySelector('h3').textContent.includes(date.slice(5)));activeDay=String(today>=0?today:0);}
  show();
 }
 function show(){Array.from(week.children).forEach((el,i)=>el.classList.toggle('mobile-day-active',i===Number(activeDay)));Array.from(days.children).forEach((b,i)=>b.setAttribute('aria-pressed',String(i===Number(activeDay))));}
 new MutationObserver(dayMode).observe(week,{childList:true});dayMode();
 window.addEventListener('pagehide',()=>{});
})();
