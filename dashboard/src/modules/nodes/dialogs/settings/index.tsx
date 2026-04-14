import {
    type SettingsDialogProps,
    SettingsDialog,
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
    AlertCard,
} from "@marzneshin/common/components";
import type { FC } from "react";
import { useTranslation } from "react-i18next";
import {
    NodeBackendType,
    NodeType,
    NodesDetailTable,
    NodesUsageWidget
} from "@marzneshin/modules/nodes";
import { NodeBackendSetting } from "./node-backend-setting";
import { FilteringTab } from "./filtering-tab";
import { AllDevicesList } from "../../devices";

interface NodesSettingsDialogProps extends SettingsDialogProps {
    entity: NodeType;
    onClose: () => void;
}

export const NodesSettingsDialog: FC<NodesSettingsDialogProps> = ({
    onOpenChange,
    open,
    entity,
    onClose,
}) => {
    const { t } = useTranslation();

    return (
        <SettingsDialog open={open} onClose={onClose} onOpenChange={onOpenChange}>
            <Tabs defaultValue="config" className="min-w-0">
                <TabsList className="w-full">
                    <TabsTrigger className="w-full" value="config">{t("config")}</TabsTrigger>
                    <TabsTrigger className="w-full" value="filtering">{t("page.nodes.filtering.tab")}</TabsTrigger>
                    <TabsTrigger className="w-full" value="info">{t("info")}</TabsTrigger>
                    <TabsTrigger className="w-full" value="devices">{t("devices")}</TabsTrigger>
                </TabsList>
                <TabsContent value="filtering">
                    <FilteringTab node={entity} />
                </TabsContent>
                <TabsContent value="config">
                    {entity.backends.length === 0 ? (
                        <AlertCard
                            variant="warning"
                            desc={t('page.nodes.settings.no-backend-alert.desc')}
                            title={t('page.nodes.settings.no-backend-alert.title')}
                        />
                    ) : (
                        <Tabs
                            className="my-3 w-full h-full"
                            defaultValue={entity.backends[0].name}
                        >
                            <TabsList className="w-full">
                                {...entity.backends.map((backend: NodeBackendType) => (
                                    <TabsTrigger
                                        className="capitalize w-full"
                                        value={backend.name}
                                        key={backend.name}
                                    >
                                        {backend.name}
                                    </TabsTrigger>
                                ))}
                            </TabsList>
                            {...entity.backends.map((backend: NodeBackendType) => (
                                <TabsContent
                                    className="w-full"
                                    value={backend.name}
                                    key={backend.name}
                                >
                                    <NodeBackendSetting node={entity} backend={backend.name} />
                                </TabsContent>
                            ))}
                        </Tabs>
                    )}
                </TabsContent>
                <TabsContent value="info">
                    <div className="space-y-5 mt-2">
                        <div>
                            <h2 className="text-sm font-semibold text-foreground mb-3">
                                {t("page.nodes.settings.detail")}
                            </h2>
                            <NodesDetailTable node={entity} />
                        </div>
                        <NodesUsageWidget node={entity} />
                    </div>
                </TabsContent>
                <TabsContent value="devices" className="min-w-0 overflow-hidden">
                    <div className="mt-2 min-w-0 overflow-hidden">
                        <AllDevicesList nodeId={entity.id} />
                    </div>
                </TabsContent>
            </Tabs>
        </SettingsDialog>
    );
};
