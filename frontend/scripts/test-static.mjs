import { readFile } from 'node:fs/promises';
import { stripTypeScriptTypes } from 'node:module';
import assert from 'node:assert/strict';

const snapshot = {
  updated_at: 100, sources: [{id:'source',name:'Company feed',status:'ok',checked_at:100}],
  items: [1,2,3].map(id => ({id,title:`News ${id}`,source:'Company',source_id:'source',markets:id===1?['A','HK']:['US'],
    companies:[],published_at:100,first_seen_at:100,url:`https://example.org/${id}`,excerpt:'<script>alert(1)</script>'})),
};
globalThis.fetch = async () => ({ok:true,json:async () => snapshot});
const storage = new Map();
globalThis.localStorage = {getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value)};
const source = (await readFile(new URL('../src/lib/api/static.ts',import.meta.url),'utf8')).replace('import.meta.env.BASE_URL',JSON.stringify('/'));
const {staticRequest:request} = await import('data:text/javascript,'+encodeURIComponent(stripTypeScriptTypes(source)));

const hk = await request('/items?group_id=2');
assert.deepEqual(hk.data.map(x=>x.id),[1]);
const feeds = (await request('/feeds')).data;
assert.equal(feeds.find(f=>f.group_id===2).item_count,1);
const first = await request('/items?limit=2');
const next = await request(`/items?limit=2&before=${first.next_cursor}`);
assert.deepEqual([...first.data,...next.data].map(x=>x.id),[1,2,3]);
assert.ok(!first.data[0].content.includes('<script>'));
await request('/items/-/read',{method:'POST',body:JSON.stringify({ids:[1]})});
assert.equal((await request('/items?group_id=2&unread=true')).data.length,0);
await request('/bookmarks',{method:'POST',body:JSON.stringify({...first.data[0],item_id:1,feed_name:'Company'})});
assert.equal((await request('/bookmarks')).data.length,1);
await request('/bookmarks/1',{method:'DELETE'});
assert.equal((await request('/bookmarks')).data.length,0);
console.log('Static adapter: market filters, counts, pagination, escaping, read state and bookmarks passed.');
