import { createLazyFileRoute } from "@tanstack/react-router";
import { TopologyPage } from "@marzneshin/modules/topology";
import { SudoRoute } from "@marzneshin/libs/sudo-routes";

export const Route = createLazyFileRoute("/_dashboard/topology")({
    component: () => (
        <SudoRoute>
            <TopologyPage />
        </SudoRoute>
    ),
});
