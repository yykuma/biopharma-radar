import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Search, X, Building2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';
import { loadCompanies } from '@/lib/api/static';
import { useUrlState } from '@/hooks/use-url-state';

const categories:Record<string,string>={biotechnology:'生物技术',pharmaceuticals:'制药',research_services:'研发服务'};

export function CompanyFilter() {
  const queryClient=useQueryClient();
  const [showMarketing,setShowMarketing]=useState(()=>{
    try{return JSON.parse(localStorage.getItem('biopharma-show-marketing') ?? 'false')===true;}catch{return false;}
  });
  const changeMarketing=(value:boolean)=>{
    setShowMarketing(value);
    localStorage.setItem('biopharma-show-marketing',JSON.stringify(value));
    void queryClient.invalidateQueries();
  };
  const {selectedCompanyId,setSelectedCompany}=useUrlState();
  const {data,error}=useQuery({queryKey:['company-catalog'],queryFn:loadCompanies,staleTime:300000});
  const [open,setOpen]=useState(false);
  const [search,setSearch]=useState('');
  const [market,setMarket]=useState('ALL');
  const companies=data?.companies ?? [];
  const selected=companies.find(c=>c.id===selectedCompanyId);
  const term=search.trim().toLocaleLowerCase();
  const filtered=companies.filter(c=>(market==='ALL' || c.listings.some(l=>l.market===market)) &&
    (!term || [c.name,c.name_zh,...c.aliases,...c.listings.map(l=>l.ticker)].join(' ').toLocaleLowerCase().includes(term)))
    .sort((a,b)=>b.news_count-a.news_count || a.name.localeCompare(b.name));
  return <>
    <div className="flex flex-wrap items-center gap-2 border-b px-4 py-2 sm:px-6">
      <Button variant="outline" size="sm" onClick={()=>setOpen(true)} className="max-w-full">
        <Building2 className="size-4 shrink-0"/><span className="truncate">{selected ? selected.name_zh || selected.name : selectedCompanyId || '按公司筛选'}</span>
      </Button>
      {selectedCompanyId ? <Button variant="ghost" size="sm" onClick={()=>setSelectedCompany(null)} aria-label="清除公司筛选"><X className="size-4"/>清除</Button> :
        <span className="text-xs text-muted-foreground">{data ? `${companies.length} 家公司 · 美股与港股` : error?'名录读取失败，可点击重试':'公司名录加载中'}</span>}
      <label className="ml-auto flex cursor-pointer items-center gap-2 text-xs text-muted-foreground"><input type="checkbox" checked={showMarketing} onChange={e=>changeMarketing(e.target.checked)} className="accent-primary"/>显示宣传内容</label>
      {selected && <a href={`${import.meta.env.BASE_URL}data/companies/${selected.id}.json`} target="_blank" rel="noreferrer" className="text-xs text-muted-foreground underline underline-offset-4">公司新闻 JSON</a>}
    </div>
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="flex max-h-[85vh] flex-col gap-3 sm:max-w-2xl">
        <DialogTitle>上市生物医药公司</DialogTitle>
        <p className="text-xs text-muted-foreground">美股 {companies.filter(c=>c.listings.some(l=>l.market==='US')).length} 家 · 港股首批 {companies.filter(c=>c.listings.some(l=>l.market==='HK')).length} 家 · 两地上市合并记录</p>
        <div className="flex gap-2">
          <div className="relative min-w-0 flex-1"><Search className="absolute left-3 top-2.5 size-4 text-muted-foreground"/><Input aria-label="搜索公司名称或股票代码" placeholder="公司名称、中文名或股票代码" value={search} onChange={e=>setSearch(e.target.value)} className="pl-9"/></div>
          <select aria-label="公司上市市场" value={market} onChange={e=>setMarket(e.target.value)} className="rounded-md border bg-background px-2 text-sm">
            <option value="ALL">美股＋港股</option><option value="US">美股</option><option value="HK">港股</option>
          </select>
        </div>
        {error && <p role="alert" className="text-sm text-destructive">名录读取失败，请刷新页面重试。</p>}
        <div className="min-h-0 overflow-y-auto divide-y" aria-label="公司搜索结果">
          {filtered.slice(0,100).map(c=><button key={c.id} onClick={()=>{setSelectedCompany(c.id);setOpen(false);}} className="flex w-full items-start justify-between gap-3 rounded-md px-2 py-3 text-left hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring">
            <span className="min-w-0"><span className="block text-sm font-medium">{c.name_zh || c.name}</span>{c.name_zh && c.name_zh!==c.name && <span className="mt-0.5 block text-xs text-muted-foreground">{c.name}</span>}
              <span className="mt-1 block text-xs text-muted-foreground">{c.listings.map(l=>`${l.exchange} ${l.ticker}`).join(' · ')} · {categories[c.category] || c.category}</span></span>
            <span className="shrink-0 text-right text-xs text-muted-foreground"><span className="block">{c.news_count} 条新闻</span>{c.official_source_ids.length>0 && <span className="mt-1 block text-emerald-700 dark:text-emerald-400">已接官方源</span>}</span>
          </button>)}
          {!filtered.length && !error && <p className="py-8 text-center text-sm text-muted-foreground">没有匹配的公司</p>}
        </div>
        <div className="flex flex-wrap justify-between gap-2 border-t pt-3 text-xs text-muted-foreground">
          <span>{filtered.length>100?`显示前 100 / ${filtered.length} 家，可搜索缩小范围`:`${filtered.length} 家匹配`} · 核对 {data?.verified_at}</span>
          <a href={`${import.meta.env.BASE_URL}data/companies.json`} target="_blank" rel="noreferrer" className="underline underline-offset-4">完整名录 JSON</a>
        </div>
        <p className="text-xs text-muted-foreground">名录覆盖不等于新闻覆盖。暂无新闻的公司仍可筛选，官方源会逐步补充。</p>
      </DialogContent>
    </Dialog>
  </>;
}
