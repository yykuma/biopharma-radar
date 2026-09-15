import type { Item, Feed, Group, Bookmark } from './types';

export interface NewsRecord {
  id: number; title: string; url: string; source: string; source_id: string;
  markets: string[]; companies: string[]; published_at: number | null;
  first_seen_at: number; excerpt: string;
}
export interface Snapshot {
  updated_at: number; last_success_at: number | null; collection_status: string;
  items: NewsRecord[]; sources: { id: string; name: string; status: string; checked_at: number; matched: number }[];
  briefing: { status: string; text: string; generated_at: number | null; references?: { number:number; title:string; url:string }[] };
}
const names = ['A 股', '港股', '美股', '全球医药'];
const markets = ['A', 'HK', 'US', 'GLOBAL'];
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
  const groups:Group[]=names.map((name,i)=>({id:i+1,name,created_at:0,updated_at:0}));
  const feedDefs=markets.flatMap((market,mi)=>data.sources.map((source,si)=>({market,source,id:(mi+1)*1000+si+1})));
  const chooseFeed=(a:NewsRecord)=>feedDefs.find(f=>f.source.id===a.source_id && a.markets.includes(f.market));
  const items:Item[]=data.items.map(a=>({id:a.id,feed_id:chooseFeed(a)?.id ?? 0,guid:a.url,title:a.title,link:a.url,
    pub_date:a.published_at ?? a.first_seen_at,created_at:a.first_seen_at,unread:!read.includes(a.id),
    content:`<p><strong>${escape(a.source)}</strong> · ${escape(a.markets.join(' / '))}${a.companies.length?' · '+escape(a.companies.join('、')):''}</p><p>${escape(a.excerpt || '该来源仅提供标题，请点击原文阅读完整报道。')}</p><p><small>以上为来源摘录。${a.published_at ? '' : '来源未提供发布时间，列表按首次发现时间排序。'}市场标签基于公司别名或来源范围。</small></p>`}));
  const feeds:Feed[]=feedDefs.filter(f=>data.items.some(a=>a.source_id===f.source.id&&a.markets.includes(f.market))).map(f=>({
    id:f.id,group_id:markets.indexOf(f.market)+1,name:f.source.name,link:data.items.find(a=>a.source_id===f.source.id)?.url ?? '',
    suspended:false,created_at:0,updated_at:data.updated_at,item_count:data.items.filter(a=>a.source_id===f.source.id&&a.markets.includes(f.market)).length,
    unread_count:data.items.filter(a=>a.source_id===f.source.id&&a.markets.includes(f.market)&&!read.includes(a.id)).length,
    fetch_state:{expires_at:0,last_checked_at:f.source.checked_at,next_check_at:0,last_http_status:f.source.status==='ok'?200:0,
      retry_after_until:0,last_success_at:f.source.status==='ok'?f.source.checked_at:0,last_error_at:0,consecutive_failures:f.source.status==='ok'?0:1}}));
  let bookmarks=local<Bookmark[]>('bookmarks',[]).map(b=>({...b,unread:!read.includes(b.item_id ?? b.id)}));
  const paginate=<U extends {id:number}>(rows:U[])=>{
    const limit=Math.min(100,Math.max(1,Number(q.get('limit'))||50));
    const offset=Math.max(0,Number(q.get('before'))||0);
    return {data:rows.slice(offset,offset+limit),total:rows.length,next_cursor:offset+limit<rows.length?String(offset+limit):null};
  };
  const matches=(a:Item|Bookmark)=>{
    const original=data.items.find(n=>n.id===('item_id' in a?a.item_id:a.id));
    const feedId=Number(q.get('feed_id'));
    const f=feedDefs.find(f=>f.id===feedId);
    return (!q.has('feed_id') || (f && original?.source_id===f.source.id && original.markets.includes(f.market))) &&
      (!q.has('group_id') || original?.markets.includes(markets[Number(q.get('group_id'))-1])) &&
      (q.get('unread')!=='true'||a.unread);
  };
  let result:unknown;
  if(method==='GET') {
    if(path==='/groups') result={data:groups,total:groups.length,next_cursor:null};
    else if(path==='/feeds') result={data:feeds,total:feeds.length,next_cursor:null};
    else if(path==='/items') result=paginate(items.filter(matches));
    else if(path.startsWith('/items/')) result={data:items.find(a=>a.id===Number(path.split('/').pop()))};
    else if(path==='/bookmarks') result=paginate(bookmarks.filter(matches));
    else if(path.startsWith('/feeds/')) result={data:feeds.find(a=>a.id===Number(path.split('/').pop()))};
    else if(path==='/search') {
      const term=(q.get('q')??'').toLocaleLowerCase();const limit=Math.min(100,Number(q.get('limit'))||10);
      result={data:{feeds:feeds.filter(f=>f.name.toLowerCase().includes(term)).slice(0,limit),
        items:items.filter(a=>`${a.title} ${a.content}`.toLowerCase().includes(term)).slice(0,limit)}};
    } else if(path==='/oidc/enabled') result={data:{enabled:false}};
    else throw new Error('此公开阅读站不支持该操作');
  } else {
    const body=typeof options.body==='string'?JSON.parse(options.body):{};
    if(path==='/items/-/read'||path==='/items/-/unread') {
      const ids=new Set(read);
      for(const id of body.ids ?? []) { if(path.endsWith('/unread')) ids.delete(id); else ids.add(id); }
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
