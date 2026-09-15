import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { loadSnapshot } from '@/lib/api/static';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';

export function RadarStatus() {
  const {data,error}=useQuery({queryKey:['radar-status'],queryFn:loadSnapshot,refetchInterval:300000});
  const [open,setOpen]=useState(false);
  if(error)return <p role="alert" className="border-b px-6 py-3 text-sm text-destructive">新闻数据读取失败，请稍后刷新重试。</p>;
  if(!data)return null;
  const stale=!data.last_success_at || Date.now()/1000-data.last_success_at>3*3600;
  const ok=data.sources.filter(s=>s.status==='ok').length;
  const openrouter=data.curation?.execution?.quota_counters?.openrouter;
  const date=(n:number|null)=>n?new Date(n*1000).toLocaleString('zh-CN',{hour12:false}):'暂无';
  return <>
    <div className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-2 sm:px-6">
      <div className="text-xs text-muted-foreground"><p>{stale?'更新已延迟 · ':''}最后采集 {date(data.last_success_at)} · 来源 {ok}/{data.sources.length}</p><p className="mt-1">中文 {data.items.filter(a=>a.title_zh).length}/{data.items.length} · 官方公告与专业媒体</p></div>
      <Button variant="outline" size="sm" onClick={()=>setOpen(true)}>AI 简报与来源状态</Button>
    </div>
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogTitle>医药新闻简报</DialogTitle>
        <p className="text-xs text-muted-foreground">生成：{date(data.briefing.generated_at)} · {data.briefing.status==='ok'?'可用':data.briefing.status==='disabled'?'未启用':'暂不可用，保留上次结果'}</p>
        <p className="whitespace-pre-wrap text-sm leading-7">{data.briefing.text}</p>
        <ol className="space-y-2 text-sm">{data.briefing.references?.map(r=><li key={r.number}><a className="text-primary underline" href={r.url} target="_blank" rel="noreferrer">[{r.number}] {r.title}</a></li>)}</ol>
        {openrouter && <p className="text-xs text-muted-foreground">OpenRouter 已计数 {openrouter.used}/{openrouter.limit} 次 · 重置时间 {date(openrouter.reset_at)}<br/>截至最近采集，包含失败请求；重置后随下次采集更新。</p>}
        <h3 className="mt-4 font-semibold">新闻来源</h3>
        <ul className="space-y-2 text-sm">{data.sources.map(s=><li key={s.id} className="flex justify-between gap-4"><span>{s.name}</span><span className="text-muted-foreground">{s.status==='ok'?`${s.matched} 条匹配`:s.status==='empty'?'暂无条目':'获取失败'}</span></li>)}</ul>
        <p className="text-xs text-muted-foreground">公司匹配以名录中的名称、别名和明确股票代码为依据，可能遗漏；“行业动态”包含未匹配公司及其他市场。原文链接供核对。</p>
      </DialogContent>
    </Dialog>
  </>;
}
