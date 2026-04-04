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
Helpers.pathsFile = LrPathUtils.child(Helpers.scriptDir, "to_delete_in_catalog.txt")
Helpers.diskDeleteFile = LrPathUtils.child(Helpers.scriptDir, "to_delete_from_disk.txt")
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

    -- Read not-in-catalog files that need disk deletion
    local diskPaths = {}
    local df = io.open(Helpers.diskDeleteFile, "r")
    if df then
        for line in df:lines() do
            local trimmed = line:match("^%s*(.-)%s*$")
            if trimmed and #trimmed > 0 then
                diskPaths[#diskPaths + 1] = trimmed
            end
        end
        df:close()
    end

    local detail = matched .. " photo(s) will be flagged as Rejected in the catalog."
    if #diskPaths > 0 then
        detail = detail .. "\n" .. #diskPaths .. " file(s) not in catalog will be moved to Trash."
    end

    local confirm = LrDialogs.confirm(
        "Process " .. (matched + #diskPaths) .. " duplicate(s)?",
        detail .. "\n\nCatalog photos will be flagged as Rejected. After that, use\nPhoto → Delete Rejected Photos to remove them from the catalog.",
        "Proceed",
        "Cancel"
    )
    if confirm ~= "ok" then return end

    -- Flag catalog photos as Rejected
    local rejected = 0
    catalog:withWriteAccessDo("Flag duplicates as rejected", function()
        for _, photo in ipairs(photosToRemove) do
            photo:setRawMetadata("pickStatus", -1)
            rejected = rejected + 1
        end
    end)

    -- Delete not-in-catalog files and move needs-import files via Python
    local diskDeleted = #diskPaths
    local pyArgs = {}
    if diskDeleted > 0 then pyArgs[#pyArgs + 1] = "--delete-from-disk" end
    pyArgs[#pyArgs + 1] = "--move-needs-import"

    local cmd = '/bin/zsh -l -c "'
        .. "export PATH=/Users/girish/.local/bin:$PATH"
        .. " && cd " .. Helpers.scriptDir
        .. " && uv run utils.py " .. table.concat(pyArgs, " ")
        .. '"'
    LrTasks.execute(cmd)

    -- Clear the catalog paths file
    local fOut = io.open(Helpers.pathsFile, "w")
    if fOut then fOut:close() end

    local msg = "Flagged " .. rejected .. " photo(s) as Rejected."
    if diskDeleted > 0 then
        msg = msg .. "\nMoved " .. diskDeleted .. " file(s) to Trash (not in catalog)."
    end
    msg = msg .. "\n\nTo finish removal, go to:\nPhoto → Delete Rejected Photos"
    msg = msg .. "\n\nIf any keepers were not in your catalog, they have been\nmoved to the to_import/ folder for easy import."

    LrDialogs.message("Done", msg, "info")
end

return Helpers
