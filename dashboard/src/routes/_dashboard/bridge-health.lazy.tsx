import { createLazyFileRoute } from "@tanstack/react-router";
import { BridgeHealthPage } from "@marzneshin/modules/bridge-health";
import { SudoRoute } from "@marzneshin/libs/sudo-routes";

export const Route = createLazyFileRoute("/_dashboard/bridge-health")({
    component: () => (
        <SudoRoute>
            <BridgeHealthPage />
        </SudoRoute>
    ),
});
