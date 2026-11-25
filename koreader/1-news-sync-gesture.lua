-- KOReader user patch: adds "Sync news feeds" to the gesture actions, so one gesture runs News Downloader.
-- Copy to koreader/patches/1-news-sync-gesture.lua on the reader and restart KOReader.
-- Then pick it in Gesture manager, under General.
local userpatch = require("userpatch")

userpatch.registerPatchPluginFunc("news_downloader", function(NewsDownloader)
    require("dispatcher"):registerAction("news_downloader_sync", {
        category = "none", event = "SyncNewsFeeds", title = "Sync news feeds", general = true,
    })
    function NewsDownloader:onSyncNewsFeeds()
        self:lazyInitialization()
        require("ui/network/manager"):runWhenOnline(function() self:loadConfigAndProcessFeedsWithUI() end)
        return true
    end
end)
