import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faShieldHalved } from '@fortawesome/free-solid-svg-icons';

export const HeaderLogo = () => {
    return <div className="flex flex-row gap-2 justify-center items-center px-4 py-2 h-10 font-bold bg-gradient-to-br from-primary/10 to-secondary/10 rounded-2xl font-header text-primary-foreground border border-border/50 shadow-lg hover:shadow-xl transition-all duration-300 backdrop-blur-xl hover:border-primary/30">
        <FontAwesomeIcon icon={faShieldHalved} className="w-5 h-5 text-primary-foreground" />
        <span className="hidden md:inline text-base tracking-wide">MARZNESHIN</span>
    </div>;
}
