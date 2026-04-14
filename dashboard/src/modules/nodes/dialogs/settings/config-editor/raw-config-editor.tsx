import { type FC, useCallback, useState } from "react";
import Editor from "@monaco-editor/react";
import { useTheme } from "@marzneshin/features/theme-switch";
import { Badge } from "@marzneshin/common/components";

interface RawConfigEditorProps {
    value: string;
    onChange: (value: string) => void;
}

export const RawConfigEditor: FC<RawConfigEditorProps> = ({
    value,
    onChange,
}) => {
    const { theme } = useTheme();
    const [valid, setValid] = useState(true);

    const handleChange = useCallback(
        (val: string | undefined) => {
            if (val === undefined) return;
            onChange(val);
            try {
                JSON.parse(val);
                setValid(true);
            } catch {
                setValid(false);
            }
        },
        [onChange]
    );

    const handleValidation = useCallback((markers: unknown[]) => {
        setValid(markers.length === 0);
    }, []);

    return (
        <div className="space-y-2">
            {!valid && (
                <Badge variant="destructive" className="text-xs">
                    Invalid JSON
                </Badge>
            )}
            <Editor
                height="50vh"
                language="json"
                className="rounded-sm border"
                theme={theme === "dark" ? "vs-dark" : "light"}
                value={value}
                onChange={handleChange}
                onValidate={handleValidation}
                options={{
                    minimap: { enabled: false },
                    fontSize: 13,
                    tabSize: 4,
                    automaticLayout: true,
                    wordWrap: "on",
                    scrollBeyondLastLine: false,
                    padding: { top: 12, bottom: 12 },
                    scrollbar: {
                        verticalScrollbarSize: 8,
                    },
                }}
            />
        </div>
    );
};
