local LrDialogs = import "LrDialogs"
local LrTasks   = import "LrTasks"
local Helpers   = require "Helpers"

LrTasks.startAsyncTask(function()
    -- Clear any previous paths
    local f = io.open(Helpers.pathsFile, "w")
    if f then f:close() end

    local exitCode = Helpers.shellRunWithProgress(
        "uv run derivative_deduplicator.py --delete_in_lightroom",
        "Derivative deduplicator (removing)..."
    )

    local output = Helpers.readSummary()

    if exitCode ~= 0 then
        LrDialogs.message("Script error", "Exit code " .. exitCode .. "\n\n" .. output, "warning")
        return
    end

    LrDialogs.message("Derivative Deduplicator", output, "info")
    Helpers.removeFromCatalog()
end)
