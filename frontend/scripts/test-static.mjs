import { readFile } from 'node:fs/promises';
import { stripTypeScriptTypes } from 'node:module';
import assert from 'node:assert/strict';

const snapshot = {
  updated_at: 100, sources: [
    {id:'source',name:'A-share collection',publisher:'Company feed',status:'ok',checked_at:100},
    {id:'other',name:'HK collection',publisher:'Company feed',status:'ok',checked_at:100}],
  items: [1,2,3].map(id => ({id,title:`News ${id}`,source:'Company',source_id:id===3?'other':'source',markets:id===1?['HK','US']:['US'],
    company_ids:id===3?['us-other']:['us-lly'],title_zh:id===2?'中文试验结果':undefined,summary_zh:id===2?'试验未达到主要终点。':undefined,content_type:id===1?'brief':'news', companies:[],published_at:100,first_seen_at:100,url:`https://example.org/${id}`,excerpt:id===1?'':'<script>alert(1)</script>'})),
};
globalThis.fetch = async () => ({ok:true,json:async () => snapshot});
const storage = new Map();
globalThis.localStorage = {getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value)};
const source = (await readFile(new URL('../src/lib/api/static.ts',import.meta.url),'utf8')).replaceAll('import.meta.env.BASE_URL',JSON.stringify('/'));
const {staticRequest:request} = await import('data:text/javascript,'+encodeURIComponent(stripTypeScriptTypes(source)));

const groups=(await request('/groups')).data;
assert.deepEqual(groups.map(g=>g.name),['美股','港股','行业动态']);
assert.ok(!groups.some(g=>g.id===1));
const hk = await request('/items?group_id=2');
assert.deepEqual(await request('/stats'),{total:3,unread:3});
assert.deepEqual(hk.data.map(x=>x.id),[1]);
const feeds = (await request('/feeds')).data;
assert.equal(feeds.find(f=>f.group_id===2).item_count,1);
assert.equal(hk.data[0].feed_id,feeds.find(f=>f.group_id===2).id);
assert.equal(feeds.filter(f=>f.group_id===3).length,1);
assert.equal(feeds.find(f=>f.group_id===3).name,'Company feed');
const usFeed=feeds.find(f=>f.group_id===3);
assert.equal(usFeed.item_count,3);
assert.deepEqual((await request(`/items?feed_id=${usFeed.id}`)).data.map(a=>a.id),[1,2,3]);
assert.equal(hk.data[0].content_type,'brief');
assert.equal(hk.data[0].summary,'');
assert.ok(hk.data[0].content.includes('class="radar-note"'));
assert.ok(!hk.data[0].content.includes('完整报道'));
const first = await request('/items?limit=2');
const next = await request(`/items?limit=2&before=${first.next_cursor}`);
assert.deepEqual([...first.data,...next.data].map(x=>x.id),[1,2,3]);
assert.ok(!first.data[0].content.includes('<script>'));
assert.ok(first.data[1].content.includes('&lt;script&gt;'));
assert.equal(first.data[1].content_type,'news');
await request('/items/-/read',{method:'POST',body:JSON.stringify({ids:[1]})});
assert.deepEqual(await request('/stats'),{total:3,unread:2});
assert.equal((await request('/items?group_id=2&unread=true')).data.length,0);
await request('/bookmarks',{method:'POST',body:JSON.stringify({...first.data[0],item_id:1,feed_name:'Company'})});
assert.equal((await request('/bookmarks')).data.length,1);
assert.equal((await request('/bookmarks')).data[0].content_type,'brief');
await request('/bookmarks/1',{method:'DELETE'});
assert.equal((await request('/bookmarks')).data.length,0);
assert.equal((await request('/items?company_id=us-lly')).total,2);
assert.equal((await request('/items?company_id=us-lly&group_id=2')).total,1);
assert.equal((await request('/items?company_id=us-other&group_id=2')).total,0);
assert.equal((await request('/items?company_id=unknown')).total,0);
const chinese=(await request('/items/2')).data;
assert.equal(chinese.title,'中文试验结果');
assert.equal(chinese.summary,'试验未达到主要终点。');
assert.ok(chinese.content.includes('查看原文标题与摘录'));
await request('/bookmarks',{method:'POST',body:JSON.stringify({...chinese,item_id:2})});
assert.equal((await request('/bookmarks?company_id=us-lly')).total,1);
assert.equal((await request('/bookmarks?company_id=us-other')).total,0);
assert.equal((await request('/bookmarks')).data[0].title,'中文试验结果');
console.log('Static adapter: market filters, counts, pagination, escaping, read state and bookmarks passed.');

// Group after filters and before pagination; retained reports stay addressable.
storage.clear();
snapshot.items[0].event_id='event-a';
snapshot.items[1].event_id='event-a';
snapshot.items[2].editorial={category:'marketing',confidence:'high'};
assert.deepEqual(await request('/stats'),{total:1,unread:1});
assert.equal((await request('/items?limit=1')).total,1);
assert.equal((await request('/items?limit=1')).next_cursor,null);
assert.equal((await request('/items')).data[0].related_articles.length,1);
assert.equal((await request('/items')).data[0].title,'中文试验结果');
assert.equal((await request('/items/2')).data.id,2);
assert.ok((await request('/items/2')).data.content.includes('同一事件'));
assert.equal((await request('/items?company_id=us-other')).total,0);
assert.equal((await request('/items?include_marketing=true')).total,2);
storage.set('biopharma-show-marketing','true');
assert.equal((await request('/items?company_id=us-other')).total,1);
assert.equal((await request('/items?company_id=us-other')).data[0].editorial_category,'marketing');
storage.set('biopharma-show-marketing','false');
await request('/items/-/read',{method:'POST',body:JSON.stringify({ids:[1]})});
assert.equal((await request('/items/2')).data.unread,false);
assert.deepEqual(await request('/stats'),{total:1,unread:0});
assert.equal((await request('/items?unread=true')).total,0);
await request('/items/-/unread',{method:'POST',body:JSON.stringify({ids:[2]})});
assert.equal((await request('/items?group_id=2')).total,1);
snapshot.items[2].editorial.confidence='uncertain';
assert.equal((await request('/items')).total,2);
console.log('Curation adapter: event pagination, linked originals, market/company filters, marketing visibility and grouped read state passed.');

// A market count must not add the same event once per publisher.
storage.clear();
snapshot.sources[1].publisher='Other publisher';
snapshot.items[2].event_id='event-a';
delete snapshot.items[2].editorial;
assert.equal((await request('/groups')).data.find(g=>g.id===3).unread_count,1);
assert.equal((await request('/items?group_id=3')).total,1);
await request('/items/-/read',{method:'POST',body:JSON.stringify({ids:[1]})});
assert.equal((await request('/groups')).data.find(g=>g.id===3).unread_count,0);
assert.equal((await request('/items/3')).data.unread,false);
console.log('Market counts deduplicate across publishers and follow grouped read state.');
