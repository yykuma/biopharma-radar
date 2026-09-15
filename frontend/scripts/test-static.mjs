import { readFile } from 'node:fs/promises';
import { stripTypeScriptTypes } from 'node:module';
import assert from 'node:assert/strict';

const snapshot = {
  updated_at: 100, sources: [
    {id:'source',name:'A-share collection',publisher:'Company feed',status:'ok',checked_at:100},
    {id:'other',name:'HK collection',publisher:'Company feed',status:'ok',checked_at:100}],
  items: [1,2,3].map(id => ({id,title:`News ${id}`,source:'Company',source_id:id===3?'other':'source',markets:id===1?['A','HK']:['US'],
    content_type:id===1?'brief':'news', companies:[],published_at:100,first_seen_at:100,url:`https://example.org/${id}`,excerpt:id===1?'':'<script>alert(1)</script>'})),
};
globalThis.fetch = async () => ({ok:true,json:async () => snapshot});
const storage = new Map();
globalThis.localStorage = {getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value)};
const source = (await readFile(new URL('../src/lib/api/static.ts',import.meta.url),'utf8')).replace('import.meta.env.BASE_URL',JSON.stringify('/'));
const {staticRequest:request} = await import('data:text/javascript,'+encodeURIComponent(stripTypeScriptTypes(source)));

const hk = await request('/items?group_id=2');
assert.deepEqual(await request('/stats'),{total:3,unread:3});
assert.deepEqual(hk.data.map(x=>x.id),[1]);
const feeds = (await request('/feeds')).data;
assert.equal(feeds.find(f=>f.group_id===2).item_count,1);
assert.equal(hk.data[0].feed_id,feeds.find(f=>f.group_id===2).id);
assert.equal(feeds.filter(f=>f.group_id===3).length,1);
assert.equal(feeds.find(f=>f.group_id===3).name,'Company feed');
const usFeed=feeds.find(f=>f.group_id===3);
assert.equal(usFeed.item_count,2);
assert.deepEqual((await request(`/items?feed_id=${usFeed.id}`)).data.map(a=>a.id),[2,3]);
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
console.log('Static adapter: market filters, counts, pagination, escaping, read state and bookmarks passed.');
