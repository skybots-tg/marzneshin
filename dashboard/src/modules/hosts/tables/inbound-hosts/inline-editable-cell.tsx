import { useState, useRef, useEffect, useCallback } from "react"
import { useQueryClient, useQuery } from "@tanstack/react-query"
import { Input } from "@marzneshin/common/components"
import {
    HostType,
    useHostsUpdateMutation,
    fetchHost,
    HostQueryFetchKey,
} from "@marzneshin/modules/hosts"

type FieldName = "remark" | "address" | "port" | "weight"

interface UseInlineEditOptions {
    host: HostType
    field: FieldName
    emptyFallback?: string
}

function getFieldValue(host: Record<string, any>, field: FieldName): string {
    const val = host[field]
    if (val === null || val === undefined) return ""
    return String(val)
}

export function useInlineEdit({ host, field, emptyFallback = "" }: UseInlineEditOptions) {
    const [isEditing, setIsEditing] = useState(false)
    const [value, setValue] = useState(getFieldValue(host, field))
    const inputRef = useRef<HTMLInputElement>(null)
    const updateMutation = useHostsUpdateMutation()
    const queryClient = useQueryClient()

    const { data: fullHost, refetch: refetchHost } = useQuery({
        queryKey: [HostQueryFetchKey, host.id!],
        queryFn: () => fetchHost({ queryKey: [HostQueryFetchKey, host.id!] }),
        enabled: false,
        initialData: undefined,
    })

    useEffect(() => {
        if (isEditing && inputRef.current) {
            inputRef.current.focus()
            inputRef.current.select()
        }
    }, [isEditing])

    const handleStartEdit = useCallback(async (e: React.MouseEvent) => {
        e.stopPropagation()
        if (!host.id) return
        const result = await refetchHost()
        if (result.data) {
            setValue(getFieldValue(result.data as Record<string, any>, field))
            setIsEditing(true)
        }
    }, [host.id, refetchHost, field])

    const handleSave = useCallback(async () => {
        if (!host.id || !fullHost) {
            setIsEditing(false)
            return
        }

        const trimmedValue = value.trim()
        const currentValue = getFieldValue(fullHost as Record<string, any>, field)

        if (trimmedValue === currentValue) {
            setIsEditing(false)
            return
        }

        if (!trimmedValue && field === "remark") {
            setValue(currentValue || emptyFallback)
            setIsEditing(false)
            return
        }

        let parsedValue: string | number | null = trimmedValue
        if (field === "port") {
            parsedValue = trimmedValue === "" ? null : Number(trimmedValue)
        } else if (field === "weight") {
            parsedValue = trimmedValue === "" ? null : Number(trimmedValue)
        }

        setIsEditing(false)

        queryClient.setQueriesData<{ entities: HostType[], pageCount: number }>(
            { queryKey: ["inbounds"] },
            (old) => {
                if (!old?.entities) return old
                return {
                    ...old,
                    entities: old.entities.map((e) =>
                        e.id === host.id ? { ...e, [field]: parsedValue } : e
                    ),
                }
            }
        )

        try {
            await updateMutation.mutateAsync({
                hostId: host.id,
                host: { ...fullHost, [field]: parsedValue },
            })
        } catch {
            queryClient.invalidateQueries({ queryKey: ["inbounds"] })
        }
    }, [host.id, fullHost, value, field, emptyFallback, updateMutation, queryClient])

    const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === "Enter") {
            e.preventDefault()
            handleSave()
        } else if (e.key === "Escape") {
            setValue(getFieldValue(host, field))
            setIsEditing(false)
        }
    }, [handleSave, host, field])

    return {
        isEditing,
        value,
        setValue,
        inputRef,
        isPending: updateMutation.isPending,
        handleStartEdit,
        handleSave,
        handleKeyDown,
    }
}

interface InlineEditableCellProps {
    host: HostType
    field: FieldName
    inputType?: string
    displayValue?: string
    emptyFallback?: string
}

export const InlineEditableCell = ({
    host,
    field,
    inputType = "text",
    displayValue,
    emptyFallback = "",
}: InlineEditableCellProps) => {
    const {
        isEditing,
        value,
        setValue,
        inputRef,
        isPending,
        handleStartEdit,
        handleSave,
        handleKeyDown,
    } = useInlineEdit({ host, field, emptyFallback })

    if (isEditing) {
        return (
            <Input
                ref={inputRef}
                type={inputType}
                value={value}
                onChange={(e) => setValue(e.target.value)}
                onBlur={handleSave}
                onKeyDown={handleKeyDown}
                onClick={(e) => e.stopPropagation()}
                onMouseDown={(e) => e.stopPropagation()}
                className="h-8"
                disabled={isPending}
            />
        )
    }

    const display = displayValue ?? (getFieldValue(host, field) || emptyFallback)

    return (
        <span
            className="cursor-pointer hover:underline"
            onClick={handleStartEdit}
        >
            {display}
        </span>
    )
}
