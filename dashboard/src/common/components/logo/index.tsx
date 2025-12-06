import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faShieldHalved } from '@fortawesome/free-solid-svg-icons';

export const HeaderLogo = () => {
    return <div className="flex flex-row gap-2 justify-center items-center px-3 py-2 h-10 text-xl font-bold bg-gradient-to-br from-primary/10 to-secondary/10 rounded-lg font-header text-primary border-2 border-primary/30 shadow-[0_0_10px_rgba(0,200,200,0.2)] hover:shadow-[0_0_20px_rgba(0,200,200,0.3)] dark:shadow-[0_0_15px_rgba(0,255,255,0.3)] dark:hover:shadow-[0_0_25px_rgba(0,255,255,0.5)] transition-all duration-300 backdrop-blur-sm hover:border-primary/50">
        <FontAwesomeIcon icon={faShieldHalved} className="w-5 h-5" />
        <span className="hidden md:inline text-base tracking-wider">MARZNESHIN</span>
    </div>;
}
