import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faShieldHalved } from '@fortawesome/free-solid-svg-icons';

export const HeaderLogo = () => {
    return <div className="flex flex-row gap-2 justify-center items-center p-2 h-10 text-2xl font-bold bg-gradient-to-br from-primary/20 to-secondary/20 rounded-lg font-header text-primary border-2 border-primary/50 shadow-[0_0_15px_rgba(0,255,255,0.3)] hover:shadow-[0_0_25px_rgba(0,255,255,0.5)] transition-all duration-300 backdrop-blur-sm">
        <FontAwesomeIcon icon={faShieldHalved} className="w-5 h-5" />
        <span className="hidden md:inline text-lg tracking-wider">MARZNESHIN</span>
    </div>;
}
