import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faShieldHalved } from '@fortawesome/free-solid-svg-icons';

export const HeaderLogo = () => {
    return <div className="glass-button flex flex-row gap-2 justify-center items-center px-4 py-2 h-10 font-semibold rounded-xl text-foreground">
        <FontAwesomeIcon icon={faShieldHalved} className="w-5 h-5 text-primary" />
        <span className="hidden md:inline text-base">MARZNESHIN</span>
    </div>;
}
