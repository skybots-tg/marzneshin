import {
    HostType,
    fetchHosts,
    fetchHost,
    HostQueryFetchKey,
    HostsOrderDialog,
    useHostsCreationMutation,
} from '@marzneshin/modules/hosts';
import { useNavigate } from "@tanstack/react-router";
import { useState, useCallback } from 'react';
import {
    useInboundsQuery,
} from '@marzneshin/modules/inbounds';
import { SidebarEntityTable, useRowSelection } from '@marzneshin/libs/entity-table';
import { columns } from './columns';
import { useDialog } from '@marzneshin/common/hooks';
import {
    InboundNotSelectedAlertDialog
} from './inbound-not-selected-alert-dialog';
import {
    InboundCardHeader,
    InboundCardContent,
} from "./inbound-sidebar-card";
import { Button } from "@marzneshin/common/components";
import { ArrowUpDown } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { BulkActionsToolbar } from "./bulk-actions-toolbar";

export const InboundHostsTable = () => {
    const { t } = useTranslation();
    const { data } = useInboundsQuery({ page: 1, size: 100 })
    const [selectedInbound, setSelectedInbound] = useState<string | undefined>(data.entities[0]?.id !== undefined ? String(data.entities[0].id) : undefined)
    const navigate = useNavigate({ from: "/hosts" })
    const [inboundSelectionAlert, setInboundSelectionAlert] = useDialog();
    const [orderDialogOpen, setOrderDialogOpen] = useState(false);
    const rowSelection = useRowSelection({});
    const createMutation = useHostsCreationMutation();
    const queryClient = useQueryClient();

    const onEdit = (entity: HostType) => navigate({ to: "/hosts/$hostId/edit", params: { hostId: String(entity.id) } });
    const onDelete = (entity: HostType) => navigate({ to: "/hosts/$hostId/delete", params: { hostId: String(entity.id) } });
    const onOpen = (entity: HostType) => navigate({ to: "/hosts/$hostId/edit", params: { hostId: String(entity.id) } });
    const getRowClassName = useCallback((entity: HostType) => {
        return entity.is_disabled ? "opacity-50" : undefined;
    }, []);

    const onDuplicate = useCallback(async (entity: HostType) => {
        if (!entity.id || !entity.inboundId) return;
        const fullHost = await fetchHost({ queryKey: [HostQueryFetchKey, entity.id] });
        const { id: _id, inboundId: _inboundId, protocol: _protocol, ...hostData } = fullHost;
        await createMutation.mutateAsync({
            inboundId: entity.inboundId,
            host: { ...hostData, remark: `${hostData.remark} (copy)` },
        });
        queryClient.invalidateQueries({ queryKey: ["inbounds"] });
    }, [createMutation, queryClient]);

    const onCreate = () => {
        if (selectedInbound) {
            navigate({
                to: "/hosts/$inboundId/create",
                params: {
                    inboundId: selectedInbound,
                }
            })
        } else {
            setInboundSelectionAlert(true)
        }
    };

    return (
        <div className="w-full">
            <InboundNotSelectedAlertDialog
                open={inboundSelectionAlert}
                onOpenChange={setInboundSelectionAlert}
            />
            <HostsOrderDialog
                open={orderDialogOpen}
                onOpenChange={setOrderDialogOpen}
            />
            <SidebarEntityTable
                fetchEntity={fetchHosts}
                entityKey="inbounds"
                secondaryEntityKey="hosts"
                sidebarEntities={data.entities}
                sidebarEntityId={selectedInbound}
                columnsFn={columns}
                filteredColumn='remark'
                defaultSortBy="weight"
                defaultSortDesc={false}
                setSidebarEntityId={setSelectedInbound}
                onCreate={onCreate}
                onOpen={onOpen}
                onEdit={onEdit}
                onDelete={onDelete}
                onDuplicate={onDuplicate}
                rowSelection={rowSelection}
                getRowClassName={getRowClassName}
                sidebarCardProps={{
                    header: InboundCardHeader,
                    content: InboundCardContent
                }}
                extraActions={
                    <>
                        <BulkActionsToolbar />
                        <Button
                            variant="outline"
                            onClick={() => setOrderDialogOpen(true)}
                            className="gap-2"
                            title={t("page.hosts.order.title", "Manage Servers Order")}
                        >
                            <ArrowUpDown className="h-4 w-4" />
                            <span className="hidden sm:inline">{t("page.hosts.order.button", "Order")}</span>
                        </Button>
                    </>
                }
            />
        </div>
    )
}
