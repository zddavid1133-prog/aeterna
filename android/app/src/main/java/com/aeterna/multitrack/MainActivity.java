package com.aeterna.multitrack;

import android.os.Bundle;
import android.view.WindowManager;
import android.webkit.WebView;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        // Prevent screen dimming/sleeping during live performance
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        // Enable Chrome remote debugging (inspect via chrome://inspect on PC)
        WebView.setWebContentsDebuggingEnabled(true);
    }
}
