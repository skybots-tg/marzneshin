import type { FC } from "react";
import { useMemo, useCallback } from "react";
import {
    ServicesQueryFetchKey,
    fetchServices,
    ServiceType
} from "@marzneshin/modules/services";
import { columns as columnsFn } from "./columns";
import { EntityTable } from "@marzneshin/libs/entity-table";
import { useNavigate } from "@tanstack/react-router";

export const ServicesTable: FC = () => {
    const navigate = useNavigate({ from: "/services" });
    
    const onEdit = useCallback((entity: ServiceType) => {
        navigate({
            to: "/services/$serviceId/edit",
            params: { serviceId: String(entity.id) },
        })
    }, [navigate]);

    const onDelete = useCallback((entity: ServiceType) => {
        navigate({
            to: "/services/$serviceId/delete",
            params: { serviceId: String(entity.id) },
        })
    }, [navigate]);

    const onOpen = useCallback((entity: ServiceType) => {
        navigate({
            to: "/services/$serviceId",
            params: { serviceId: String(entity.id) },
        })
    }, [navigate]);

    const onCreate = useCallback(() => {
        navigate({ to: "/services/create" });
    }, [navigate]);

    const columns = useMemo(
        () => columnsFn({ onEdit, onDelete, onOpen }),
        [onEdit, onDelete, onOpen]
    );

    return (
        <EntityTable
            fetchEntity={fetchServices}
            columns={columns}
            primaryFilter="name"
            entityKey={ServicesQueryFetchKey}
            onCreate={onCreate}
            onOpen={onOpen}
        />
    );
};
