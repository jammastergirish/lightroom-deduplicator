--[[
    RemoveFromCatalog.lua
    Reads deleted_paths.txt (written by the Python deduplicator scripts)
    and removes matching photos from the Lightroom catalog.

    The plugin removes photos from the catalog only — the Python scripts
    handle filesystem deletion when run with --delete, or the user can
    use --lightroom to let this plugin handle both.
]]

local LrApplication = import "LrApplication"
local LrDialogs     = import "LrDialogs"
local LrTasks       = import "LrTasks"
local LrPathUtils   = import "LrPathUtils"
local LrFileUtils   = import "LrFileUtils"
local LrProgressScope = import "LrProgressScope"

-- The deleted_paths.txt file lives next to this plugin
local pluginDir = _PLUGIN.path
local parentDir = LrPathUtils.parent(pluginDir)
local pathsFile = LrPathUtils.child(parentDir, "deleted_paths.txt")

LrTasks.startAsyncTask(function()

    -- Read the paths file
    if not LrFileUtils.exists(pathsFile) then
        LrDialogs.message(
            "No paths file found",
            "Expected: " .. pathsFile .. "\n\nRun the deduplicator scripts with --lightroom or --delete first.",
            "warning"
        )
        return
    end

    local f = io.open(pathsFile, "r")
    if not f then
        LrDialogs.message("Error", "Could not open " .. pathsFile, "critical")
        return
    end

    local pathSet = {}
    local pathCount = 0
    for line in f:lines() do
        local trimmed = line:match("^%s*(.-)%s*$")
        if trimmed and #trimmed > 0 then
            pathSet[trimmed] = true
            pathCount = pathCount + 1
        end
    end
    f:close()

    if pathCount == 0 then
        LrDialogs.message("Nothing to do", "deleted_paths.txt is empty.", "info")
        return
    end

    -- Build lookup of catalog photos
    local catalog = LrApplication.activeCatalog()
    local photosToRemove = {}

    local progress = LrProgressScope({ title = "Scanning catalog for duplicates to remove" })

    catalog:withReadAccessDo(function()
        local allPhotos = catalog:getAllPhotos()
        progress:setPortionComplete(0, #allPhotos)

        for i, photo in ipairs(allPhotos) do
            if progress:isCanceled() then return end
            local photoPath = photo:getRawMetadata("path")
            if pathSet[photoPath] then
                photosToRemove[#photosToRemove + 1] = photo
                pathSet[photoPath] = nil  -- mark as matched
            end
            if i % 1000 == 0 then
                progress:setPortionComplete(i, #allPhotos)
            end
        end
    end)

    progress:done()

    local matched = #photosToRemove
    local unmatched = 0
    for _ in pairs(pathSet) do unmatched = unmatched + 1 end

    if matched == 0 then
        local msg = "No matching photos found in the catalog."
        if unmatched > 0 then
            msg = msg .. "\n\n" .. unmatched .. " path(s) in the file were not in the catalog (already removed or not imported)."
        end
        LrDialogs.message("Nothing to remove", msg, "info")
        return
    end

    -- Confirm
    local detail = matched .. " photo(s) will be removed from the catalog."
    if unmatched > 0 then
        detail = detail .. "\n" .. unmatched .. " path(s) were not found in the catalog (already removed or not imported)."
    end

    local confirm = LrDialogs.confirm(
        "Remove " .. matched .. " duplicate(s) from catalog?",
        detail,
        "Remove",
        "Cancel"
    )
    if confirm ~= "ok" then return end

    -- Remove from catalog
    catalog:withWriteAccessDo("Remove duplicates from catalog", function()
        for _, photo in ipairs(photosToRemove) do
            catalog:removePhoto(photo)
        end
    end)

    -- Clear the paths file after successful removal
    local fOut = io.open(pathsFile, "w")
    if fOut then fOut:close() end

    LrDialogs.message(
        "Done",
        "Removed " .. matched .. " photo(s) from the Lightroom catalog.\ndeleted_paths.txt has been cleared.",
        "info"
    )
end)
