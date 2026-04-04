return {
    LrSdkVersion = 6.0,
    LrSdkMinimumVersion = 6.0,
    LrToolkitIdentifier = "com.dedup.remove-from-catalog",
    LrPluginName = "Deduplicator",
    LrLibraryMenuItems = {
        {
            title = "Remove Strict Duplicates",
            file = "StrictRemove.lua",
        },
        {
            title = "Remove Derivative Duplicates",
            file = "DerivativeRemove.lua",
        },
    },
    VERSION = { major = 1, minor = 0, revision = 0 },
}
