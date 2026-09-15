import { Search, Settings, Rss } from "lucide-react";

import { FeedList } from "@/components/feed/feed-list";
import { useI18n } from "@/lib/i18n";

import { useUIStore } from "@/store";

export function Sidebar() {
  const { t } = useI18n();
  const { setSearchOpen, setSettingsOpen } = useUIStore();

  return (
    <aside className="sidebar-typography flex h-full w-75 flex-none flex-col overflow-hidden border-r bg-sidebar text-sidebar-foreground">
      {/* Header */}
      <div className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
        <img
          src={`${import.meta.env.BASE_URL}icon-96.png`}
          alt={t("common.fusionLogo")}
          width={32}
          height={32}
          className="h-8 w-8 rounded-md"
        />
        <span className="text-base font-semibold">医药动态</span>
      </div>

      {/* Search button */}
      <div className="px-2 pt-3">
        <button
          className="flex w-full items-center justify-between rounded-md bg-muted px-3 py-2 text-muted-foreground transition-colors hover:bg-accent"
          onClick={() => setSearchOpen(true)}
        >
          <div className="flex items-center gap-2">
            <Search className="h-4 w-4" />
            <span className="text-sm">{t("sidebar.search")}</span>
          </div>
          <kbd className="rounded bg-accent px-1.5 py-0.5 font-mono text-[11px] font-medium">
            Cmd+K / ?
          </kbd>
        </button>
      </div>

      {/* Feed list */}
      <FeedList />

      {/* Footer */}
      <div className="p-2">
        <a href={`${import.meta.env.BASE_URL}api.html`} target="_blank" rel="noreferrer" className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent/50"><Rss className="h-4 w-4" />数据接口 / RSS</a>
        <p className="px-2 py-1 text-xs text-muted-foreground">收藏与已读仅保存在当前浏览器。</p>
        <button
          className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-accent/50"
          onClick={() => setSettingsOpen(true)}
        >
          <Settings className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span>{t("sidebar.settings")}</span>
        </button>
      </div>
    </aside>
  );
}
