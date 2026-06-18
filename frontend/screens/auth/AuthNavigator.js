import React, { useState } from 'react';
import ForgotPasswordScreen from './ForgotPasswordScreen';
import LoginScreen from './LoginScreen';
import RegisterScreen from './RegisterScreen';
import VerifyEmailScreen from './VerifyEmailScreen';

export default function AuthNavigator() {
  const [screen, setScreen] = useState('login');
  const [resetToken, setResetToken] = useState('');
  const [verifyToken, setVerifyToken] = useState('');

  if (screen === 'register') {
    return <RegisterScreen onLogin={() => setScreen('login')} />;
  }
  if (screen === 'forgot') {
    return <ForgotPasswordScreen onLogin={() => setScreen('login')} initialToken={resetToken} />;
  }
  if (screen === 'verify') {
    return <VerifyEmailScreen onDone={() => setScreen('login')} initialToken={verifyToken} />;
  }
  return (
    <LoginScreen
      onRegister={() => setScreen('register')}
      onForgot={() => setScreen('forgot')}
      onOtp={() => setScreen('login')}
    />
  );
}
