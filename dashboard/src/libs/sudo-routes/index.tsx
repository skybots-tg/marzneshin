import { useAuth } from "@marzneshin/modules/auth";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useState, PropsWithChildren, FC } from "react";

export const SudoRoute: FC<PropsWithChildren> = ({ children }) => {
    const { isSudo, isLoggedIn } = useAuth();
    const navigate = useNavigate();
    const [verified, setVerified] = useState(false);

    useEffect(() => {
        const checkAccess = async () => {
            const loggedIn = await isLoggedIn();
            if (!loggedIn || !isSudo()) {
                navigate({ to: '/login' });
            } else {
                setVerified(true);
            }
        };

        checkAccess();
    }, [isSudo, isLoggedIn, navigate]);

    if (!verified) {
        return null;
    }

    return children;
};

