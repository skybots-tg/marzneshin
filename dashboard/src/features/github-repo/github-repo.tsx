import {
    Card,
    CardTitle,
    CardContent,
    CardDescription,
    Button,
} from "@marzneshin/common/components"
import { type FC } from "react";
import {
    GithubIcon,
    StarIcon,
} from "lucide-react";
import { projectInfo } from "@marzneshin/common/utils";

interface GithubRepoProps {
    variant?: "full" | "mini"
    stargazers_count: number;
    full_name?: string;
    description?: string;
}

export const GithubRepo: FC<GithubRepoProps> = ({ variant = "full", stargazers_count, full_name, description }) => {
    return (
        <Button variant="ghost" className="bg-background/60 backdrop-blur-xl border border-border hover:bg-accent/50 p-2 h-auto rounded-2xl" asChild>
            <Card className="border-0 shadow-none bg-transparent">
                <a href={projectInfo.github} target="_blank">
                    <CardContent className="hstack size-fit p-0 gap-2 items-center">
                        <GithubIcon className="size-6" />
                        {variant === "full" ? (
                            <div className="vstack items-start">
                                <CardTitle className="font-semibold text-xs hstack justify-between w-full gap-2 text-primary">
                                    {full_name}
                                    <div className="hstack gap-1 font-bold items-center text-xs text-foreground">
                                        <StarIcon className="size-3" />
                                        {stargazers_count}
                                    </div>
                                </CardTitle>
                                <CardDescription className="text-xs text-muted-foreground/80">
                                    {description}
                                </CardDescription>
                            </div>
                        ) : (
                            <CardDescription className="hstack gap-1 font-bold items-center text-xs">
                                <StarIcon className="size-3" />
                                {stargazers_count}
                            </CardDescription>
                        )}
                    </CardContent>
                </a>
            </Card>
        </Button>
    )
}
