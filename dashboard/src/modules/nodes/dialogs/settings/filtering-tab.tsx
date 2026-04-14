import {
    Badge,
    Button,
    Card,
    CardContent,
    CardHeader,
    CardTitle,
    Input,
    Label,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Switch,
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
} from "@marzneshin/common/components";
import type { FC } from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
    type NodeType,
    type DnsProvider,
    DnsProviders,
    useFilteringConfigQuery,
    useFilteringMutation,
    useSSHCredsQuery,
    useStoreSSHCredsMutation,
    useDeleteSSHCredsMutation,
} from "@marzneshin/modules/nodes";
import { InstallAdGuardDialog } from "./install-adguard-dialog";
import {
    Shield,
    ChevronDown,
    Server,
    KeyRound,
    Trash2,
    Save,
    Download,
} from "lucide-react";

export const FilteringTab: FC<{ node: NodeType }> = ({ node }) => {
    const { t } = useTranslation();
    const { data: config } = useFilteringConfigQuery(node.id);
    const { data: sshInfo } = useSSHCredsQuery(node.id);
    const filteringMutation = useFilteringMutation();
    const storeSSHMutation = useStoreSSHCredsMutation();
    const deleteSSHMutation = useDeleteSSHCredsMutation();

    const [adblockEnabled, setAdblockEnabled] = useState(config.adblock_enabled);
    const [dnsProvider, setDnsProvider] = useState<DnsProvider>(config.dns_provider);
    const [dnsAddress, setDnsAddress] = useState(config.dns_address || "");
    const [adguardPort, setAdguardPort] = useState(
        String(config.adguard_home_port),
    );

    const [sshUser, setSshUser] = useState("root");
    const [sshPort, setSshPort] = useState("22");
    const [sshPassword, setSshPassword] = useState("");
    const [sshKey, setSshKey] = useState("");
    const [sshAuthMethod, setSshAuthMethod] = useState<"password" | "key">(
        "password",
    );
    const [sshPin, setSshPin] = useState("");

    const [installOpen, setInstallOpen] = useState(false);
    const [adguardOpen, setAdguardOpen] = useState(false);
    const [sshOpen, setSshOpen] = useState(false);

    const showCustomInput =
        dnsProvider === "custom" || dnsProvider === "nextdns";

    const handleApply = () => {
        filteringMutation.mutate({
            nodeId: node.id,
            adblock_enabled: adblockEnabled,
            dns_provider: dnsProvider,
            dns_address: dnsAddress || null,
            adguard_home_port: Number(adguardPort) || 5353,
        });
    };

    const handleSaveSSH = () => {
        storeSSHMutation.mutate({
            nodeId: node.id,
            ssh_user: sshUser,
            ssh_port: Number(sshPort),
            ssh_password:
                sshAuthMethod === "password" ? sshPassword : undefined,
            ssh_key: sshAuthMethod === "key" ? sshKey : undefined,
            pin: sshPin,
        });
    };

    const handleDeleteSSH = () => {
        deleteSSHMutation.mutate(node.id);
    };

    return (
        <div className="space-y-4 my-4">
            {/* Ad-blocking section */}
            <Card>
                <CardHeader className="flex flex-row items-center gap-2 pb-3">
                    <Shield className="size-5" />
                    <CardTitle className="text-base">
                        {t("page.nodes.filtering.title")}
                    </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                    <div className="flex items-center justify-between">
                        <div className="space-y-0.5">
                            <Label className="text-sm font-medium">
                                {t("page.nodes.filtering.enable")}
                            </Label>
                            <p className="text-xs text-muted-foreground">
                                {t("page.nodes.filtering.enable_desc")}
                            </p>
                        </div>
                        <Switch
                            checked={adblockEnabled}
                            onCheckedChange={setAdblockEnabled}
                        />
                    </div>

                    <div className="space-y-2">
                        <Label className="text-sm font-medium">
                            {t("page.nodes.filtering.dns_provider")}
                        </Label>
                        <Select
                            value={dnsProvider}
                            onValueChange={(v) =>
                                setDnsProvider(v as DnsProvider)
                            }
                        >
                            <SelectTrigger className="w-full">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                {Object.entries(DnsProviders).map(
                                    ([key, label]) => (
                                        <SelectItem key={key} value={key}>
                                            {label}
                                        </SelectItem>
                                    ),
                                )}
                            </SelectContent>
                        </Select>
                    </div>

                    {showCustomInput && (
                        <div className="space-y-2">
                            <Label className="text-sm font-medium">
                                {dnsProvider === "nextdns"
                                    ? t("page.nodes.filtering.nextdns_id")
                                    : t("page.nodes.filtering.custom_dns")}
                            </Label>
                            <Input
                                value={dnsAddress}
                                onChange={(e) => setDnsAddress(e.target.value)}
                                placeholder={
                                    dnsProvider === "nextdns"
                                        ? "abc123"
                                        : "94.140.14.14"
                                }
                            />
                        </div>
                    )}

                    <Button
                        onClick={handleApply}
                        className="w-full"
                        disabled={filteringMutation.isPending}
                    >
                        <Save className="size-4 mr-2" />
                        {t("page.nodes.filtering.apply")}
                    </Button>
                </CardContent>
            </Card>

            {/* AdGuard Home section */}
            <Collapsible open={adguardOpen} onOpenChange={setAdguardOpen}>
                <Card>
                    <CollapsibleTrigger className="w-full">
                        <CardHeader className="flex flex-row items-center justify-between pb-3 cursor-pointer">
                            <div className="flex items-center gap-2">
                                <Server className="size-5" />
                                <CardTitle className="text-base">
                                    AdGuard Home
                                </CardTitle>
                                {config.adguard_home_installed ? (
                                    <Badge variant="positive" className="size-fit">
                                        {t("page.nodes.filtering.adguard.installed")}
                                    </Badge>
                                ) : (
                                    <Badge
                                        variant="outline"
                                        className="size-fit"
                                    >
                                        {t(
                                            "page.nodes.filtering.adguard.not_installed",
                                        )}
                                    </Badge>
                                )}
                            </div>
                            <ChevronDown
                                className={`size-4 transition-transform ${adguardOpen ? "rotate-180" : ""}`}
                            />
                        </CardHeader>
                    </CollapsibleTrigger>
                    <CollapsibleContent>
                        <CardContent className="space-y-4 pt-0">
                            <div className="space-y-2">
                                <Label className="text-sm font-medium">
                                    {t("page.nodes.filtering.adguard.port")}
                                </Label>
                                <Input
                                    type="number"
                                    value={adguardPort}
                                    onChange={(e) =>
                                        setAdguardPort(e.target.value)
                                    }
                                    placeholder="5353"
                                />
                            </div>
                            <Button
                                onClick={() => setInstallOpen(true)}
                                className="w-full"
                                variant="outline"
                                disabled={!sshInfo.exists}
                            >
                                <Download className="size-4 mr-2" />
                                {t("page.nodes.filtering.adguard.install_btn")}
                            </Button>
                            {!sshInfo.exists && (
                                <p className="text-xs text-muted-foreground text-center">
                                    {t(
                                        "page.nodes.filtering.adguard.need_ssh",
                                    )}
                                </p>
                            )}
                        </CardContent>
                    </CollapsibleContent>
                </Card>
            </Collapsible>

            {/* SSH Credentials section */}
            <Collapsible open={sshOpen} onOpenChange={setSshOpen}>
                <Card>
                    <CollapsibleTrigger className="w-full">
                        <CardHeader className="flex flex-row items-center justify-between pb-3 cursor-pointer">
                            <div className="flex items-center gap-2">
                                <KeyRound className="size-5" />
                                <CardTitle className="text-base">
                                    {t("page.nodes.filtering.ssh.title")}
                                </CardTitle>
                                {sshInfo.exists ? (
                                    <Badge variant="positive" className="size-fit">
                                        {t(
                                            "page.nodes.filtering.ssh.saved",
                                        )}
                                    </Badge>
                                ) : (
                                    <Badge
                                        variant="outline"
                                        className="size-fit"
                                    >
                                        {t(
                                            "page.nodes.filtering.ssh.not_saved",
                                        )}
                                    </Badge>
                                )}
                            </div>
                            <ChevronDown
                                className={`size-4 transition-transform ${sshOpen ? "rotate-180" : ""}`}
                            />
                        </CardHeader>
                    </CollapsibleTrigger>
                    <CollapsibleContent>
                        <CardContent className="space-y-4 pt-0">
                            {sshInfo.exists ? (
                                <div className="space-y-3">
                                    <p className="text-sm text-muted-foreground">
                                        {t(
                                            "page.nodes.filtering.ssh.stored_info",
                                        )}
                                    </p>
                                    <Button
                                        onClick={handleDeleteSSH}
                                        variant="destructive"
                                        className="w-full"
                                        disabled={
                                            deleteSSHMutation.isPending
                                        }
                                    >
                                        <Trash2 className="size-4 mr-2" />
                                        {t(
                                            "page.nodes.filtering.ssh.delete",
                                        )}
                                    </Button>
                                </div>
                            ) : (
                                <div className="space-y-3">
                                    <div className="grid grid-cols-2 gap-3">
                                        <div className="space-y-1">
                                            <Label className="text-xs">
                                                {t(
                                                    "page.nodes.filtering.ssh.user",
                                                )}
                                            </Label>
                                            <Input
                                                value={sshUser}
                                                onChange={(e) =>
                                                    setSshUser(e.target.value)
                                                }
                                            />
                                        </div>
                                        <div className="space-y-1">
                                            <Label className="text-xs">
                                                {t(
                                                    "page.nodes.filtering.ssh.port",
                                                )}
                                            </Label>
                                            <Input
                                                type="number"
                                                value={sshPort}
                                                onChange={(e) =>
                                                    setSshPort(e.target.value)
                                                }
                                            />
                                        </div>
                                    </div>

                                    <div className="space-y-1">
                                        <Label className="text-xs">
                                            {t(
                                                "page.nodes.filtering.ssh.auth_method",
                                            )}
                                        </Label>
                                        <div className="flex gap-4">
                                            <label className="flex items-center gap-2">
                                                <input
                                                    type="radio"
                                                    name="sshAuthMethodFilter"
                                                    value="password"
                                                    checked={
                                                        sshAuthMethod ===
                                                        "password"
                                                    }
                                                    onChange={() =>
                                                        setSshAuthMethod(
                                                            "password",
                                                        )
                                                    }
                                                />
                                                <span className="text-sm">
                                                    {t(
                                                        "page.nodes.filtering.ssh.password",
                                                    )}
                                                </span>
                                            </label>
                                            <label className="flex items-center gap-2">
                                                <input
                                                    type="radio"
                                                    name="sshAuthMethodFilter"
                                                    value="key"
                                                    checked={
                                                        sshAuthMethod === "key"
                                                    }
                                                    onChange={() =>
                                                        setSshAuthMethod("key")
                                                    }
                                                />
                                                <span className="text-sm">
                                                    SSH Key
                                                </span>
                                            </label>
                                        </div>
                                    </div>

                                    {sshAuthMethod === "password" ? (
                                        <div className="space-y-1">
                                            <Label className="text-xs">
                                                {t(
                                                    "page.nodes.filtering.ssh.password",
                                                )}
                                            </Label>
                                            <Input
                                                type="password"
                                                value={sshPassword}
                                                onChange={(e) =>
                                                    setSshPassword(
                                                        e.target.value,
                                                    )
                                                }
                                            />
                                        </div>
                                    ) : (
                                        <div className="space-y-1">
                                            <Label className="text-xs">
                                                SSH Key
                                            </Label>
                                            <Input
                                                value={sshKey}
                                                onChange={(e) =>
                                                    setSshKey(e.target.value)
                                                }
                                                placeholder="/path/to/key"
                                            />
                                        </div>
                                    )}

                                    <div className="space-y-1">
                                        <Label className="text-xs">
                                            {t(
                                                "page.nodes.filtering.ssh.pin",
                                            )}
                                        </Label>
                                        <Input
                                            type="password"
                                            maxLength={4}
                                            placeholder="****"
                                            value={sshPin}
                                            onChange={(e) =>
                                                setSshPin(
                                                    e.target.value
                                                        .replace(/\D/g, "")
                                                        .slice(0, 4),
                                                )
                                            }
                                        />
                                        <p className="text-xs text-muted-foreground">
                                            {t(
                                                "page.nodes.filtering.ssh.pin_desc",
                                            )}
                                        </p>
                                    </div>

                                    <Button
                                        onClick={handleSaveSSH}
                                        className="w-full"
                                        disabled={
                                            sshPin.length !== 4 ||
                                            (!sshPassword && !sshKey) ||
                                            storeSSHMutation.isPending
                                        }
                                    >
                                        <Save className="size-4 mr-2" />
                                        {t(
                                            "page.nodes.filtering.ssh.save",
                                        )}
                                    </Button>
                                </div>
                            )}
                        </CardContent>
                    </CollapsibleContent>
                </Card>
            </Collapsible>

            <InstallAdGuardDialog
                open={installOpen}
                onOpenChange={setInstallOpen}
                nodeId={node.id}
                nodeName={node.name}
            />
        </div>
    );
};
