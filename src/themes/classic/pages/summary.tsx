import { Helmet } from 'react-helmet-async';
import ActivityList from '../components/ActivityList';
import { useTheme } from '../hooks/useTheme';

const Summary = () => {
  const { theme } = useTheme();

  return (
    <>
      <Helmet>
        <html lang="en" data-theme={theme} />
      </Helmet>
      <ActivityList />
    </>
  );
};

export default Summary;
