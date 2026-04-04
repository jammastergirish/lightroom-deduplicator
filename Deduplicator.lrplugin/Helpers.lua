--[[
    Helpers.lua
    Shared utilities for the deduplicator plugin.
]]

local LrApplication   = import "LrApplication"
local LrDialogs       = import "LrDialogs"
local LrPathUtils     = import "LrPathUtils"
local LrFileUtils     = import "LrFileUtils"
local LrProgressScope = import "LrProgressScope"
local LrTasks         = import "LrTasks"

local Helpers = {}

Helpers.scriptDir = LrPathUtils.parent(_PLUGIN.path)
Helpers.catalogPath = LrApplication.activeCatalog():getPath()
Helpers.pathsFile = LrPathUtils.child(Helpers.scriptDir, "deleted_paths.txt")
Helpers.outputFile = LrPathUtils.child(Helpers.scriptDir, ".dedup_output.txt")
Helpers.progressFile = LrPathUtils.child(Helpers.scriptDir, ".dedup_progress.txt")
Helpers.summaryFile = LrPathUtils.child(Helpers.scriptDir, ".dedup_summary.txt")

local function readProgressMessage()
    local f = io.open(Helpers.progressFile, "r")
    if not f then return nil end
    local text = f:read("*l")
    f:close()
    return text
end

--- Run a shell command with a live progress bar that polls .dedup_progress.txt.
--- Returns the exit code.
function Helpers.shellRunWithProgress(cmd, progressTitle)
    local progress = LrProgressScope({ title = progressTitle })
    progress:setIndeterminate()

    local exitCode = nil

    -- Run the command in a background async task
    LrTasks.startAsyncTask(function()
        local fullCmd = '/bin/zsh -l -c "'
            .. "export PATH=/Users/girish/.local/bin:$PATH"
            .. " && cd " .. Helpers.scriptDir
            .. " && " .. cmd .. " --catalog \\\"" .. Helpers.catalogPath .. "\\\""
            .. " > " .. Helpers.outputFile .. " 2>&1"
            .. '"'
        exitCode = LrTasks.execute(fullCmd)
    end)

    -- Poll the progress file until the command finishes
    while exitCode == nil do
        LrTasks.sleep(0.5)
        if progress:isCanceled() then break end
        local msg = readProgressMessage()
        if msg and #msg > 0 then
            progress:setCaption(msg)
        end
    end

    progress:done()
    return exitCode or -1
end

function Helpers.readSummary()
    local f = io.open(Helpers.summaryFile, "r")
    if not f then return "No duplicates found. Library is clean!" end
    local text = f:read("*a")
    f:close()
    return text
end

function Helpers.removeFromCatalog()
    if not LrFileUtils.exists(Helpers.pathsFile) then
        LrDialogs.message("Nothing to remove", "No duplicates were found.", "info")
        return
    end

    local f = io.open(Helpers.pathsFile, "r")
    if not f then
        LrDialogs.message("Error", "Could not open " .. Helpers.pathsFile, "critical")
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
        LrDialogs.message("Nothing to remove", "No duplicates were found.", "info")
        return
    end

    local catalog = LrApplication.activeCatalog()
    local photosToRemove = {}

    local progress = LrProgressScope({ title = "Scanning catalog for duplicates..." })

    catalog:withReadAccessDo(function()
        local allPhotos = catalog:getAllPhotos()
        progress:setPortionComplete(0, #allPhotos)

        for i, photo in ipairs(allPhotos) do
            if progress:isCanceled() then return end
            local photoPath = photo:getRawMetadata("path")
            if pathSet[photoPath] then
                photosToRemove[#photosToRemove + 1] = photo
                pathSet[photoPath] = nil
            end
            if i % 1000 == 0 then
                progress:setPortionComplete(i, #allPhotos)
                progress:setCaption("Matched " .. #photosToRemove .. " so far (" .. i .. "/" .. #allPhotos .. " checked)")
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

    local detail = matched .. " photo(s) will be removed from the catalog."
    if unmatched > 0 then
        detail = detail .. "\n" .. unmatched .. " path(s) were not found in the catalog (already removed or not imported)."
    end

    local confirm = LrDialogs.confirm(
        "Flag " .. matched .. " duplicate(s) as Rejected?",
        detail .. "\n\nPhotos will be flagged as Rejected. After that, use\nPhoto → Delete Rejected Photos to remove them from the catalog.",
        "Flag as Rejected",
        "Cancel"
    )
    if confirm ~= "ok" then return end

    local rejected = 0
    catalog:withWriteAccessDo("Flag duplicates as rejected", function()
        for _, photo in ipairs(photosToRemove) do
            photo:setRawMetadata("pickStatus", -1)
            rejected = rejected + 1
        end
    end)

    local fOut = io.open(Helpers.pathsFile, "w")
    if fOut then fOut:close() end

    LrDialogs.message(
        "Done",
        "Flagged " .. rejected .. " photo(s) as Rejected.\n\n"
            .. "To finish removal, go to:\n"
            .. "Photo → Delete Rejected Photos",
        "info"
    )
end

return Helpers
