import { type FC, useState, useEffect, useCallback } from "react";
import {
    Button,
    Badge,
    Awaiting,
    ToggleGroup,
    ToggleGroupItem,
} from "@marzneshin/common/components";
import { Blocks, FileCode2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
    type NodeType,
    NodeBackendSettingConfigFormat,
    useNodesSettingsMutation,
    useNodesSettingsQuery,
} from "@marzneshin/modules/nodes";
import type { EditorMode } from "./types";
import { useBlockConfig } from "./use-block-config";
import { BlockConfigEditor } from "./block-config-editor";
import { RawConfigEditor } from "./raw-config-editor";

function parseConfig(data: {
    config: string;
    format: NodeBackendSettingConfigFormat;
}): string {
    if (data.format === NodeBackendSettingConfigFormat.JSON) {
        try {
            return JSON.stringify(JSON.parse(data.config), null, 4);
        } catch {
            return data.config;
        }
    }
    return data.config;
}

interface ConfigEditorProps {
    entity: NodeType;
    backend: string;
}

export const ConfigEditor: FC<ConfigEditorProps> = ({ entity, backend }) => {
    const { t } = useTranslation();
    const { data, isFetching } = useNodesSettingsQuery(entity, backend);
    const mutate = useNodesSettingsMutation();

    const isJson = data.format === NodeBackendSettingConfigFormat.JSON;
    const [mode, setMode] = useState<EditorMode>(isJson ? "blocks" : "raw");
    const [rawConfig, setRawConfig] = useState(() => parseConfig(data));

    const blockConfig = useBlockConfig(isJson ? parseConfig(data) : "{}");

    useEffect(() => {
        if (!isFetching && data.config) {
            const parsed = parseConfig(data);
            setRawConfig(parsed);
            if (isJson) blockConfig.syncFromConfig(parsed);
        }
    }, [isFetching, data, isJson]);

    const handleModeChange = useCallback(
        (val: string) => {
            if (!val) return;
            const newMode = val as EditorMode;
            if (newMode === "raw" && mode === "blocks") {
                setRawConfig(blockConfig.toConfigString());
            } else if (newMode === "blocks" && mode === "raw") {
                blockConfig.syncFromConfig(rawConfig);
            }
            setMode(newMode);
        },
        [mode, rawConfig, blockConfig]
    );

    const handleSave = useCallback(() => {
        const config = mode === "blocks"
            ? blockConfig.toConfigString()
            : rawConfig;
        mutate.mutate({ node: entity, backend, config, format: data.format });
    }, [mode, blockConfig, rawConfig, entity, backend, data.format, mutate]);

    const canSave = mode === "blocks" ? !blockConfig.hasErrors : true;

    return (
        <Awaiting
            isFetching={isFetching}
            Component={
                <div className="space-y-3">
                    <div className="flex items-center justify-between gap-2">
                        {isJson && (
                            <ToggleGroup
                                type="single"
                                value={mode}
                                onValueChange={handleModeChange}
                                size="sm"
                                className="h-8"
                            >
                                <ToggleGroupItem
                                    value="blocks"
                                    className="h-7 gap-1.5 px-2.5 text-xs"
                                >
                                    <Blocks className="size-3.5" />
                                    {t("blocks", { defaultValue: "Blocks" })}
                                </ToggleGroupItem>
                                <ToggleGroupItem
                                    value="raw"
                                    className="h-7 gap-1.5 px-2.5 text-xs"
                                >
                                    <FileCode2 className="size-3.5" />
                                    Raw JSON
                                </ToggleGroupItem>
                            </ToggleGroup>
                        )}

                        {mode === "blocks" && blockConfig.errorCount > 0 && (
                            <Badge variant="destructive" className="text-xs">
                                {blockConfig.errorCount} {blockConfig.errorCount === 1 ? "error" : "errors"}
                            </Badge>
                        )}
                    </div>

                    {mode === "blocks" && isJson ? (
                        <BlockConfigEditor
                            blocks={blockConfig.blocks}
                            onToggleCollapse={blockConfig.toggleCollapse}
                            onDuplicate={blockConfig.duplicateBlock}
                            onRemove={blockConfig.removeBlock}
                            onUpdateRaw={blockConfig.updateBlockRaw}
                            onUpdateItem={blockConfig.updateItem}
                            onDuplicateItem={blockConfig.duplicateItem}
                            onRemoveItem={blockConfig.removeItem}
                            onReorderItems={blockConfig.reorderItems}
                            onAddItem={blockConfig.addItem}
                            onAddSection={blockConfig.addBlock}
                            onCollapseAll={blockConfig.collapseAll}
                            onExpandAll={blockConfig.expandAll}
                        />
                    ) : (
                        <RawConfigEditor
                            value={rawConfig}
                            onChange={setRawConfig}
                        />
                    )}

                    <Button
                        className="w-full"
                        variant={!canSave ? "destructive" : "default"}
                        onClick={handleSave}
                        disabled={!canSave || mutate.isPending}
                    >
                        {t("save")}
                    </Button>
                </div>
            }
        />
    );
};
