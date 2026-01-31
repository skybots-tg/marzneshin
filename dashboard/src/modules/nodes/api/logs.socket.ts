import { NodeType } from "@marzneshin/modules/nodes";
import useWebSocket, { ReadyState } from "react-use-websocket";
import { useAuth } from "@marzneshin/modules/auth";
import { useCallback, useEffect, useRef, useState } from "react";

export const MAX_NUMBER_OF_LOGS = 200;

export const getStatus = (status: string) => {
    return {
        [ReadyState.CONNECTING]: "connecting",
        [ReadyState.OPEN]: "connected",
        [ReadyState.CLOSING]: "closed",
        [ReadyState.CLOSED]: "closed",
        [ReadyState.UNINSTANTIATED]: "closed",
    }[status];
};

export const getWebsocketUrl = (nodeId: number, backend: string) => {
    try {
        const baseURL = new URL(
            import.meta.env.VITE_BASE_API.startsWith("/")
                ? window.location.origin + import.meta.env.VITE_BASE_API
                : import.meta.env.VITE_BASE_API,
        );
        
        // Build the path properly, ensuring no double slashes
        const basePath = baseURL.pathname.endsWith('/') 
            ? baseURL.pathname.slice(0, -1) 
            : baseURL.pathname;
        const wsPath = `${basePath}/nodes/${nodeId}/${backend}/logs`;
        
        // Create WebSocket URL
        const wsProtocol = baseURL.protocol === "https:" ? "wss:" : "ws:";
        const wsUrl = new URL(wsPath, baseURL);
        wsUrl.protocol = wsProtocol;
        wsUrl.searchParams.set('token', useAuth.getState().getAuthToken() || '');
        
        return wsUrl.toString();
    } catch (e) {
        console.error("Unable to generate websocket url");
        console.error(e);
        return null;
    }
};

export const useNodesLog = (node: NodeType, backend: string) => {
    const [logs, setLogs] = useState<string[]>([]);
    const logsDiv = useRef<HTMLDivElement | null>(null);
    const scrollShouldStayOnEnd = useRef(true);

    const updateLogs = useCallback(
        (callback: (prevLogs: string[]) => string[]) => {
            setLogs((prevLogs) => {
                const newLogs = callback(prevLogs);
                return newLogs.length > MAX_NUMBER_OF_LOGS
                    ? newLogs.slice(-MAX_NUMBER_OF_LOGS)
                    : newLogs;
            });
        },
        [],
    );

    const { readyState } = useWebSocket(
        node?.id ? getWebsocketUrl(node.id, backend) : "",
        {
            onMessage: (e: any) => {
                updateLogs((prevLogs) => [...prevLogs, e.data]);
            },
            shouldReconnect: () => true,
            reconnectAttempts: 10,
            reconnectInterval: 1000,
        },
    );

    useEffect(() => {
        if (logsDiv.current && scrollShouldStayOnEnd.current) {
            logsDiv.current.scrollTop = logsDiv.current.scrollHeight;
        }
    }, [logs]);

    useEffect(() => {
        return () => {
            setLogs([]);
        };
    }, []);

    const status = getStatus(readyState.toString());

    return { status, readyState, logs, logsDiv };
}; 
