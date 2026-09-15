import type { Item, Feed, Group, Bookmark } from './types';

export interface NewsRecord {
  id: number; title: string; url: string; source: string; source_id: string;
  markets: string[]; companies: string[]; published_at: number | null;
  first_seen_at: number; excerpt: string;
  company_ids?: string[]; title_zh?: string; summary_zh?: string; source_kind?: string;
  event_id?: string; related_article_ids?: number[];
  editorial?: {category:string; confidence:string};
  translation?: {status: string; method?: string; basis?: string};
  publisher?: string; content_type?: 'brief' | 'news';
}
export interface Snapshot {
  updated_at: number; last_success_at: number | null; collection_status: string;
  items: NewsRecord[]; sources: { id: string; name: string; publisher?: string; status: string; checked_at: number; matched: number }[];
  briefing: { status: string; text: string; generated_at: number | null; references?: { number:number; title:string; url:string }[] };
}
export interface Company {
  id:string; name:string; name_zh?:string; aliases:string[]; category:string;
  listings:{market:string; ticker:string; exchange:string}[];
  news_count:number; official_source_ids:string[]; verified_at:string;
}
export interface CompanyCatalog {verified_at:string; companies:Company[]}
export async function loadCompanies():Promise<CompanyCatalog> {
  const response=await fetch(`${import.meta.env.BASE_URL}data/companies.json`);
  if(!response.ok)throw new Error('公司名录读取失败');
  return response.json();
}
const marketGroups = [
  {id:3,market:'US',name:'美股'},
  {id:2,market:'HK',name:'港股'},
  {id:4,market:'GLOBAL',name:'行业动态'},
];
let cached: Promise<Snapshot> | null = null;
let loadedAt = 0;
export function loadSnapshot(): Promise<Snapshot> {
  if (!cached || Date.now() - loadedAt > 300000) {
    loadedAt = Date.now();
    cached = fetch(`${import.meta.env.BASE_URL}data/latest.json`, { cache:'no-cache' }).then(async r => {
      if (!r.ok) throw new Error('新闻快照读取失败，请稍后刷新');
      const data: Snapshot = await r.json();
      if (!Array.isArray(data.items)) throw new Error('新闻数据格式异常');
      return data;
    }).catch(e => { cached=null; throw e; });
  }
  return cached;
}
function local<T>(key:string, fallback:T):T {
  try { return JSON.parse(localStorage.getItem(`biopharma-${key}`) ?? 'null') ?? fallback; }
  catch { return fallback; }
}
function save(key:string, value:unknown) { localStorage.setItem(`biopharma-${key}`,JSON.stringify(value)); }
const escape = (s:string) => s.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));

export async function staticRequest<T>(endpoint:string, options:RequestInit = {}):Promise<T> {
  const url = new URL(endpoint,'https://reader.local');
  const path=url.pathname; const q=url.searchParams; const method=options.method ?? 'GET';
  if (path==='/feeds/refresh') { cached=null; await loadSnapshot(); return undefined as T; }
  const data=await loadSnapshot();
  const read=local<number[]>('read',[]);
  const includeMarketing=q.get('include_marketing')==='true' || local<boolean>('show-marketing',false);
  const visible=(a:NewsRecord)=>includeMarketing || a.editorial?.category!=='marketing' || a.editorial?.confidence!=='high';
  const eventKey=(a:NewsRecord)=>a.event_id ?? String(a.id);
  const byId=new Map(data.items.map(a=>[a.id,a]));
  const byEvent=new Map<string,NewsRecord[]>();
  for(const a of data.items){const key=eventKey(a);byEvent.set(key,[...(byEvent.get(key) ?? []),a]);}
  const eventCount=(rows:NewsRecord[])=>new Set(rows.map(eventKey)).size;
  const peers=(a:NewsRecord)=>(byEvent.get(eventKey(a)) ?? []).filter(b=>b.id!==a.id);
  const related=(a:NewsRecord)=>peers(a).filter(b=>/^https?:\/\//i.test(b.url)).map(b=>({id:b.id,title:b.title_zh || b.title,link:b.url,source:b.publisher || b.source}));
  const relatedContent=(a:NewsRecord)=>{
    const rows=related(a);
    return rows.length ? `<details><summary>同一事件 · 另有 ${rows.length} 篇报道</summary><ul>${rows.map(b=>`<li><a href="${escape(b.link)}" target="_blank" rel="noopener noreferrer">${escape(b.title)}</a> · ${escape(b.source)}</li>`).join('')}</ul></details>` : '';
  };
  if (path==='/stats' && method==='GET') {
    return {total:eventCount(data.items.filter(visible)),unread:eventCount(data.items.filter(a=>visible(a)&&!read.includes(a.id)))} as T;
  }
  const groups:Group[]=marketGroups.map(({id,name})=>({id,name,created_at:0,updated_at:0}));
  const publishers = [...new Set(data.sources.map(s=>s.publisher ?? s.name))].map(name=>{
    const sources=data.sources.filter(s=>(s.publisher ?? s.name)===name);
    return {name, sources, slot:data.sources.indexOf(sources[0])+1};
  });
  const feedDefs=marketGroups.flatMap(({market,id:groupId})=>publishers.map(p=>({market,groupId,...p,id:groupId*1000+p.slot})));
  const belongs=(a:NewsRecord,f:typeof feedDefs[number])=>f.sources.some(s=>s.id===a.source_id)&&a.markets.includes(f.market);
  const chooseFeed=(a:NewsRecord)=>{
    const candidates=feedDefs.filter(f=>belongs(a,f));
    return candidates.find(f=>f.id===Number(q.get('feed_id')))
      ?? candidates.find(f=>f.groupId===Number(q.get('group_id'))) ?? candidates[0];
  };
  const items:Item[]=data.items.map(a=>({id:a.id,feed_id:chooseFeed(a)?.id ?? 0,guid:a.url,title:a.title_zh || a.title,link:a.url,
    summary:a.summary_zh || a.excerpt,content_type:a.content_type ?? 'news',
    related_articles:related(a),editorial_category:a.editorial?.category,
    pub_date:a.published_at ?? a.first_seen_at,created_at:a.first_seen_at,unread:!read.includes(a.id),
    content:`${(a.summary_zh || a.excerpt).split('\n').filter(Boolean).map(p=>`<p>${escape(p)}</p>`).join('')}<p class="radar-note">${a.source_kind==='company_release'?'公司公告 · ':''}${a.title_zh ? (a.translation?.method==='editorial'?'中文编译':'AI 中文编译') : a.excerpt?'来源摘录':'仅标题，可查看原文'}${a.published_at?'':' · 时间为收录时间'}</p>${relatedContent(a)}${a.title_zh?`<details><summary>查看原文标题与摘录</summary><p>${escape(a.title)}</p><p>${escape(a.excerpt)}</p></details>`:''}`}));
  const feeds:Feed[]=feedDefs.filter(f=>data.items.some(a=>belongs(a,f))).map(f=>{
    const entries=data.items.filter(a=>belongs(a,f)&&visible(a));
    const checkedAt=Math.max(...f.sources.map(s=>s.checked_at));
    const healthy=f.sources.every(s=>s.status==='ok');
    return {
      id:f.id,group_id:f.groupId,name:f.name,link:entries[0]?.url ?? '',
      suspended:false,created_at:0,updated_at:data.updated_at,item_count:eventCount(entries),
      unread_count:eventCount(entries.filter(a=>!read.includes(a.id))),
      fetch_state:{expires_at:0,last_checked_at:checkedAt,next_check_at:0,last_http_status:healthy?200:0,
        retry_after_until:0,last_success_at:healthy?checkedAt:0,last_error_at:0,consecutive_failures:healthy?0:1}};
  });
  let bookmarks=local<Bookmark[]>('bookmarks',[]).map(b=>{
    const item=items.find(a=>a.id===(b.item_id ?? b.id));
    return {...b,...(item?{title:item.title,content:item.content,summary:item.summary,content_type:item.content_type,related_articles:item.related_articles,editorial_category:item.editorial_category,feed_id:item.feed_id}:{}),unread:!read.includes(b.item_id ?? b.id)};
  });
  const paginate=<U extends {id:number}>(rows:U[])=>{
    const limit=Math.min(100,Math.max(1,Number(q.get('limit'))||50));
    const offset=Math.max(0,Number(q.get('before'))||0);
    return {data:rows.slice(offset,offset+limit),total:rows.length,next_cursor:offset+limit<rows.length?String(offset+limit):null};
  };
  const matches=(a:Item|Bookmark)=>{
    const original=byId.get(('item_id' in a?a.item_id:a.id) ?? 0);
    const feedId=Number(q.get('feed_id'));
    const f=feedDefs.find(f=>f.id===feedId);
    return (!q.has('feed_id') || (f && original && belongs(original,f))) &&
      (!q.has('group_id') || original?.markets.includes(marketGroups.find(g=>g.id===Number(q.get('group_id')))?.market ?? '')) &&
      (!q.has('company_id') || original?.company_ids?.includes(q.get('company_id')!)) &&
      (q.get('unread')!=='true'||a.unread);
  };
  const grouped=(rows:Item[])=>{
    const groups=new Map<string,Item[]>();
    for(const item of rows){
      const original=byId.get(item.id)!;
      if(!visible(original))continue;
      const key=eventKey(original);
      groups.set(key,[...(groups.get(key) ?? []),item]);
    }
    return [...groups.values()].map(rows=>{
      const preferred=rows.find(a=>byId.get(a.id)?.title_zh) ?? rows[0];
      return {...preferred,unread:rows.some(a=>a.unread)};
    });
  };
  let result:unknown;
  if(method==='GET') {
    if(path==='/groups') result={data:groups,total:groups.length,next_cursor:null};
    else if(path==='/feeds') result={data:feeds,total:feeds.length,next_cursor:null};
    else if(path==='/items') result=paginate(grouped(items.filter(matches)));
    else if(path.startsWith('/items/')) result={data:items.find(a=>a.id===Number(path.split('/').pop()))};
    else if(path==='/bookmarks') result=paginate(bookmarks.filter(matches));
    else if(path.startsWith('/feeds/')) result={data:feeds.find(a=>a.id===Number(path.split('/').pop()))};
    else if(path==='/search') {
      const term=(q.get('q')??'').toLocaleLowerCase();const limit=Math.min(100,Number(q.get('limit'))||10);
      result={data:{feeds:feeds.filter(f=>f.name.toLowerCase().includes(term)).slice(0,limit),
        items:grouped(items.filter(a=>`${a.title} ${a.content}`.toLowerCase().includes(term))).slice(0,limit)}};
    } else if(path==='/oidc/enabled') result={data:{enabled:false}};
    else throw new Error('此公开阅读站不支持该操作');
  } else {
    const body=typeof options.body==='string'?JSON.parse(options.body):{};
    if(path==='/items/-/read'||path==='/items/-/unread') {
      const ids=new Set(read);
      for(const id of body.ids ?? []) {
        const original=byId.get(id);
        const affected=original ? [original,...peers(original)].map(a=>a.id) : [id];
        for(const itemId of affected){ if(path.endsWith('/unread')) ids.delete(itemId); else ids.add(itemId); }
      }
      save('read',[...ids]);
    } else if(path==='/bookmarks'&&method==='POST') {
      const existing=bookmarks.find(b=>b.item_id===body.item_id);
      const item=items.find(a=>a.id===body.item_id);
      const bookmark:Bookmark=existing ?? {...body,id:body.item_id ?? Date.now(),feed_id:item?.feed_id ?? null,created_at:Math.floor(Date.now()/1000),unread:item?.unread ?? false};
      if(!existing)bookmarks=[bookmark,...bookmarks];save('bookmarks',bookmarks);result={data:bookmark};
    } else if(path.startsWith('/bookmarks/')&&method==='DELETE') {
      save('bookmarks',bookmarks.filter(b=>b.id!==Number(path.split('/').pop())));
    } else throw new Error('新闻源由网站维护者统一配置。');
  }
  return result as T;
}
