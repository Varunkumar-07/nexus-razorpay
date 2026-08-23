import { NavLink } from "react-router-dom";

export default function Header({ subtitle }) {
  return (
    <header>
      <div className="header-top">
        <h1>
          NEXUS <span>— Northlight Outdoors</span>
        </h1>
        <nav className="nav-links">
          <NavLink to="/" end className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
            Chat with NEXUS
          </NavLink>
          <NavLink to="/products" className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
            Browse Products
          </NavLink>
        </nav>
      </div>
      <p className="subtitle">{subtitle}</p>
    </header>
  );
}
