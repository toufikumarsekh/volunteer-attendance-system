async function startWebAuthnRegistration(userId) {
  try {
    const response = await fetch(`/auth/begin-registration?user_id=${userId}`);
    const options = await response.json();

    options.publicKey.challenge = bufferDecode(options.publicKey.challenge);
    options.publicKey.user.id = bufferDecode(options.publicKey.user.id);

    const credential = await navigator.credentials.create({
      publicKey: options.publicKey
    });

    const credentialData = {
      user_id: userId,
      credentialId: arrayBufferToBase64(credential.rawId),
      publicKey: arrayBufferToBase64(credential.response.attestationObject)
    };

    const res = await fetch('/auth/finish-registration', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(credentialData)
    });

    const result = await res.json();
    if (!res.ok) throw new Error(result.error || 'Registration failed');

  } catch (err) {
    alert("Fingerprint registration failed: " + err);
    console.error(err);
  }
}

function bufferDecode(value) {
  return Uint8Array.from(atob(value), c => c.charCodeAt(0));
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  return btoa(String.fromCharCode(...bytes));
}
